"""Business logic kept out of the route handlers so it is easy to test."""

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.models import Activity, Lead, LeadStatus, Role, User


def log_activity(db: Session, lead: Lead, kind: str, message: str, user: User | None = None) -> None:
    db.add(Activity(lead=lead, kind=kind, message=message, user_id=user.id if user else None))


def pick_agent_round_robin(db: Session) -> User | None:
    """Route a new lead to the active agent with the fewest open leads (ties -> lowest id)."""
    open_statuses = [LeadStatus.new, LeadStatus.contacted, LeadStatus.qualified]
    open_count = (
        select(func.count(Lead.id))
        .where(Lead.assigned_to_id == User.id, Lead.status.in_(open_statuses))
        .correlate(User)
        .scalar_subquery()
    )
    stmt = (
        select(User)
        .where(User.role == Role.agent, User.is_active.is_(True))
        .order_by(open_count.asc(), User.id.asc())
        .limit(1)
    )
    return db.scalars(stmt).first()


def find_duplicate(db: Session, email: str | None, phone: str | None) -> Lead | None:
    conditions = []
    if email:
        conditions.append(func.lower(Lead.email) == email.lower())
    if phone:
        conditions.append(Lead.phone == normalize_phone(phone))
    if not conditions:
        return None
    return db.scalars(select(Lead).where(or_(*conditions)).limit(1)).first()


def normalize_phone(phone: str | None) -> str | None:
    if phone is None:
        return None
    digits = "".join(ch for ch in phone if ch.isdigit() or ch == "+")
    return digits or None
