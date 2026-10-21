from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session, selectinload

from app.database import get_db
from app.deps import get_current_user, require_roles
from app.models import ALLOWED_TRANSITIONS, Lead, LeadStatus, Role, User
from app.schemas import (
    AssignLead,
    LeadCreate,
    LeadDetail,
    LeadOut,
    LeadPage,
    LeadUpdate,
    NoteCreate,
    PipelineStats,
    StatusChange,
)
from app.services import find_duplicate, log_activity, normalize_phone, pick_agent_round_robin

router = APIRouter(prefix="/leads", tags=["leads"])


def _get_visible_lead(db: Session, lead_id: int, user: User) -> Lead:
    lead = db.scalars(
        select(Lead).options(selectinload(Lead.activities)).where(Lead.id == lead_id)
    ).first()
    if not lead:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Lead not found")
    # Agents may only see leads assigned to them.
    if user.role == Role.agent and lead.assigned_to_id != user.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Lead not found")
    return lead


@router.post("", response_model=LeadOut, status_code=status.HTTP_201_CREATED)
def create_lead(payload: LeadCreate, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    if find_duplicate(db, payload.email, payload.phone):
        raise HTTPException(status.HTTP_409_CONFLICT, "A lead with this email or phone already exists")
    lead = Lead(
        full_name=payload.full_name,
        email=payload.email.lower() if payload.email else None,
        phone=normalize_phone(payload.phone),
        source=payload.source,
        campaign=payload.campaign,
    )
    agent = pick_agent_round_robin(db)
    if agent:
        lead.assigned_to_id = agent.id
    db.add(lead)
    db.flush()
    log_activity(db, lead, "created", f"Lead created from source '{lead.source}'", user)
    if agent:
        log_activity(db, lead, "assigned", f"Auto-assigned to {agent.full_name}", user)
    db.commit()
    db.refresh(lead)
    return lead


@router.get("", response_model=LeadPage)
def list_leads(
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
    status_filter: LeadStatus | None = Query(default=None, alias="status"),
    source: str | None = None,
    q: str | None = Query(default=None, description="Search name, email or phone"),
    page: int = Query(default=1, ge=1),
    size: int = Query(default=20, ge=1, le=100),
):
    stmt = select(Lead)
    if user.role == Role.agent:
        stmt = stmt.where(Lead.assigned_to_id == user.id)
    if status_filter:
        stmt = stmt.where(Lead.status == status_filter)
    if source:
        stmt = stmt.where(Lead.source == source)
    if q:
        like = f"%{q.lower()}%"
        stmt = stmt.where(
            or_(func.lower(Lead.full_name).like(like), func.lower(Lead.email).like(like), Lead.phone.like(like))
        )
    total = db.scalar(select(func.count()).select_from(stmt.subquery()))
    items = db.scalars(stmt.order_by(Lead.created_at.desc(), Lead.id.desc()).offset((page - 1) * size).limit(size)).all()
    return LeadPage(items=items, total=total or 0, page=page, size=size)


@router.get("/stats", response_model=PipelineStats)
def pipeline_stats(
    db: Session = Depends(get_db),
    _: User = Depends(require_roles(Role.admin, Role.manager)),
):
    by_status = dict(db.execute(select(Lead.status, func.count()).group_by(Lead.status)).all())
    by_source = dict(db.execute(select(Lead.source, func.count()).group_by(Lead.source)).all())
    total = sum(by_status.values())
    converted = by_status.get(LeadStatus.converted, 0)
    return PipelineStats(
        total=total,
        by_status={s.value: by_status.get(s, 0) for s in LeadStatus},
        by_source=by_source,
        conversion_rate=round(converted / total, 4) if total else 0.0,
    )


@router.get("/{lead_id}", response_model=LeadDetail)
def get_lead(lead_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    return _get_visible_lead(db, lead_id, user)


@router.patch("/{lead_id}", response_model=LeadOut)
def update_lead(
    lead_id: int, payload: LeadUpdate, db: Session = Depends(get_db), user: User = Depends(get_current_user)
):
    lead = _get_visible_lead(db, lead_id, user)
    changes = payload.model_dump(exclude_unset=True)
    if "phone" in changes:
        changes["phone"] = normalize_phone(changes["phone"])
    if "email" in changes and changes["email"]:
        changes["email"] = changes["email"].lower()
    for field, value in changes.items():
        setattr(lead, field, value)
    if changes:
        log_activity(db, lead, "updated", "Updated: " + ", ".join(sorted(changes)), user)
    db.commit()
    db.refresh(lead)
    return lead


@router.post("/{lead_id}/status", response_model=LeadOut)
def change_status(
    lead_id: int, payload: StatusChange, db: Session = Depends(get_db), user: User = Depends(get_current_user)
):
    lead = _get_visible_lead(db, lead_id, user)
    if payload.status not in ALLOWED_TRANSITIONS[lead.status]:
        raise HTTPException(
            422,
            f"Cannot move lead from '{lead.status.value}' to '{payload.status.value}'",
        )
    old = lead.status
    lead.status = payload.status
    msg = f"Status {old.value} -> {payload.status.value}"
    if payload.note:
        msg += f": {payload.note}"
    log_activity(db, lead, "status", msg, user)
    db.commit()
    db.refresh(lead)
    return lead


@router.post("/{lead_id}/assign", response_model=LeadOut)
def assign_lead(
    lead_id: int,
    payload: AssignLead,
    db: Session = Depends(get_db),
    user: User = Depends(require_roles(Role.admin, Role.manager)),
):
    lead = _get_visible_lead(db, lead_id, user)
    agent = db.get(User, payload.user_id)
    if not agent or not agent.is_active or agent.role != Role.agent:
        raise HTTPException(422, "Target must be an active agent")
    lead.assigned_to_id = agent.id
    log_activity(db, lead, "assigned", f"Assigned to {agent.full_name}", user)
    db.commit()
    db.refresh(lead)
    return lead


@router.post("/{lead_id}/notes", response_model=LeadDetail, status_code=status.HTTP_201_CREATED)
def add_note(lead_id: int, payload: NoteCreate, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    lead = _get_visible_lead(db, lead_id, user)
    log_activity(db, lead, "note", payload.message, user)
    db.commit()
    db.refresh(lead)
    return lead


@router.delete("/{lead_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_lead(
    lead_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(require_roles(Role.admin)),
):
    lead = _get_visible_lead(db, lead_id, user)
    db.delete(lead)
    db.commit()
