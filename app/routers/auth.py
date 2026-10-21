from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.database import get_db
from app.deps import get_current_user
from app.models import Role, User
from app.schemas import Token, UserCreate, UserOut
from app.security import create_access_token, hash_password, verify_password

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/bootstrap", response_model=UserOut, status_code=status.HTTP_201_CREATED)
def bootstrap_admin(payload: UserCreate, db: Session = Depends(get_db)):
    """Create the very first admin account. Disabled once any user exists."""
    if db.scalar(select(func.count(User.id))):
        raise HTTPException(status.HTTP_409_CONFLICT, "Bootstrap already completed")
    user = User(
        email=payload.email.lower(),
        full_name=payload.full_name,
        hashed_password=hash_password(payload.password),
        role=Role.admin,
    )
    db.add(user)
    db.commit()
    return user


@router.post("/token", response_model=Token)
def login(form: OAuth2PasswordRequestForm = Depends(), db: Session = Depends(get_db)):
    user = db.scalars(select(User).where(User.email == form.username.lower())).first()
    if not user or not user.is_active or not verify_password(form.password, user.hashed_password):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Incorrect email or password")
    return Token(access_token=create_access_token(str(user.id), user.role.value))


@router.get("/me", response_model=UserOut)
def me(user: User = Depends(get_current_user)):
    return user
