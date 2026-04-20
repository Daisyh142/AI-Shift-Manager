from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone

import jwt
from fastapi import APIRouter, Depends, Header, HTTPException
from passlib.context import CryptContext
from sqlmodel import Session, select

from ..db import get_session
from ..models import User
from ..schemas import (
    LoginRequest,
    RegisterRequest,
    TokenResponse,
    UserResponse,
)

router = APIRouter(prefix="/auth", tags=["auth"])

pwd_ctx = CryptContext(schemes=["pbkdf2_sha256"], deprecated="auto")

SECRET_KEY = os.getenv("JWT_SECRET", "dev-secret-change-me-in-production")
ALGORITHM = "HS256"
TOKEN_EXPIRE_HOURS = int(os.getenv("JWT_EXPIRE_HOURS", "24"))


def _unauthorized(message: str) -> HTTPException:
    return HTTPException(
        status_code=401,
        detail={"code": "unauthorized", "message": message},
    )


def _forbidden(message: str) -> HTTPException:
    return HTTPException(
        status_code=403,
        detail={"code": "forbidden", "message": message},
    )


def _create_token(user_id: int) -> str:
    payload = {
        "sub": str(user_id),
        "exp": datetime.now(timezone.utc) + timedelta(hours=TOKEN_EXPIRE_HOURS),
    }
    return jwt.encode(payload, SECRET_KEY, algorithm=ALGORITHM)


def _decode_token(token: str) -> int:
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        return int(payload["sub"])
    except (jwt.ExpiredSignatureError, jwt.InvalidTokenError, KeyError, ValueError):
        raise _unauthorized("Invalid or expired token")


def get_current_user_from_header(
    session: Session = Depends(get_session),
    authorization: str = Header(default=""),
) -> User:
    if not authorization.startswith("Bearer "):
        raise _unauthorized("Missing Bearer token")
    token = authorization.removeprefix("Bearer ")
    user_id = _decode_token(token)
    user = session.get(User, user_id)
    if not user:
        raise _unauthorized("User not found")
    return user


def require_owner(current_user: User = Depends(get_current_user_from_header)) -> User:
    if current_user.role != "owner":
        raise _forbidden("Owner role is required")
    return current_user


def require_employee_or_owner(current_user: User = Depends(get_current_user_from_header)) -> User:
    if current_user.role not in {"employee", "owner"}:
        raise _forbidden("Authenticated employee or owner role is required")
    return current_user


@router.post("/register", response_model=TokenResponse)
def register(body: RegisterRequest, session: Session = Depends(get_session)):
    existing = session.exec(select(User).where(User.email == body.email)).first()
    if existing:
        raise HTTPException(
            status_code=409,
            detail={"code": "conflict", "message": "Email already registered"},
        )

    user = User(
        email=body.email,
        hashed_password=pwd_ctx.hash(body.password),
        role=body.role.value,
        employee_id=body.employee_id,
    )
    session.add(user)
    session.commit()
    session.refresh(user)

    token = _create_token(user.id)
    return TokenResponse(
        access_token=token,
        user=UserResponse(
            id=user.id,
            email=user.email,
            role=user.role,
            employee_id=user.employee_id,
        ),
    )


@router.post("/login", response_model=TokenResponse)
def login(body: LoginRequest, session: Session = Depends(get_session)):
    user = session.exec(select(User).where(User.email == body.email)).first()
    if not user or not pwd_ctx.verify(body.password, user.hashed_password):
        raise _unauthorized("Invalid email or password")

    token = _create_token(user.id)
    return TokenResponse(
        access_token=token,
        user=UserResponse(
            id=user.id,
            email=user.email,
            role=user.role,
            employee_id=user.employee_id,
        ),
    )


@router.get("/me", response_model=UserResponse)
def me(current_user: User = Depends(get_current_user_from_header)):
    return UserResponse(
        id=current_user.id,
        email=current_user.email,
        role=current_user.role,
        employee_id=current_user.employee_id,
    )
