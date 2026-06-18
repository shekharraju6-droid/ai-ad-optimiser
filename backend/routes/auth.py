"""
JWT-based authentication for AdOptima.
"""
import os
from datetime import datetime, timedelta
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer, OAuth2PasswordRequestForm
from pydantic import BaseModel
from passlib.context import CryptContext
from jose import JWTError, jwt
from sqlalchemy.orm import Session

from backend.db.database import get_db
from backend.db.models import User

router = APIRouter(prefix="/api/auth", tags=["auth"])

SECRET_KEY = os.getenv("ADOPTIMA_JWT_SECRET", "change-me-in-production")
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_DAYS = 7

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/auth/login", auto_error=False)


class UserCreate(BaseModel):
    email: str
    password: str
    full_name: Optional[str] = None


class TokenResponse(BaseModel):
    access_token: str
    token_type: str
    user: dict


def verify_password(plain_password, hashed_password):
    return pwd_context.verify(plain_password, hashed_password)


def get_password_hash(password):
    return pwd_context.hash(password)


def create_access_token(data: dict, expires_delta: Optional[timedelta] = None):
    to_encode = data.copy()
    expire = datetime.utcnow() + (expires_delta or timedelta(days=ACCESS_TOKEN_EXPIRE_DAYS))
    to_encode.update({"exp": expire})
    return jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)


def get_current_user(token: str = Depends(oauth2_scheme), db: Session = Depends(get_db)) -> Optional[User]:
    if not token:
        return None
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        email: str = payload.get("sub")
        if email is None:
            return None
    except JWTError:
        return None
    return db.query(User).filter(User.email == email, User.is_active == True).first()


def get_current_user_required(user: User = Depends(get_current_user)) -> User:
    if not user:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Not authenticated")
    return user


@router.post("/register", response_model=dict)
def register(req: UserCreate, db: Session = Depends(get_db)):
    existing = db.query(User).filter(User.email == req.email).first()
    if existing:
        raise HTTPException(status_code=400, detail="Email already registered")
    user = User(
        email=req.email,
        hashed_password=get_password_hash(req.password),
        full_name=req.full_name,
        role="user",
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user.to_dict()


@router.post("/login", response_model=TokenResponse)
def login(form_data: OAuth2PasswordRequestForm = Depends(), db: Session = Depends(get_db)):
    user = db.query(User).filter(User.email == form_data.username).first()
    if not user or not verify_password(form_data.password, user.hashed_password):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid credentials")
    access_token = create_access_token(data={"sub": user.email, "role": user.role})
    return {"access_token": access_token, "token_type": "bearer", "user": user.to_dict()}


@router.get("/me", response_model=dict)
def me(user: User = Depends(get_current_user_required)):
    return user.to_dict()


@router.post("/seed-admin")
def seed_admin_user(password: str, db: Session = Depends(get_db)):
    """Convenience endpoint to create the first admin user. Disable or protect in production."""
    email = "admin@adoptima.ai"
    existing = db.query(User).filter(User.email == email).first()
    if existing:
        return {"message": "Admin already exists", "user": existing.to_dict()}
    user = User(
        email=email,
        hashed_password=get_password_hash(password),
        full_name="Admin",
        role="admin",
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return {"message": "Admin created", "user": user.to_dict()}
