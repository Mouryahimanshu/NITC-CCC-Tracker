from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.dependencies import current_user
from app.db.models import User
from app.db.postgres import get_session
from app.schemas.auth import LoginRequest, TokenResponse, UserResponse
from app.services.auth import create_access_token, verify_password

router = APIRouter(prefix="/auth", tags=["authentication"])


@router.post("/login", response_model=TokenResponse)
def login(payload: LoginRequest, db: Session = Depends(get_session)):
    user = db.scalar(select(User).where(User.username == payload.username.strip().lower(), User.active.is_(True)))
    if user is None or not verify_password(payload.password, user.password_hash):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid username or password")
    safe_user = UserResponse(
        id=str(user.id), username=user.username,
        display_name=user.display_name, role=user.role,
    )
    return TokenResponse(access_token=create_access_token(user.id, user.role), user=safe_user)


@router.get("/me", response_model=UserResponse)
def me(user: User = Depends(current_user)):
    return UserResponse(
        id=str(user.id), username=user.username,
        display_name=user.display_name, role=user.role,
    )
