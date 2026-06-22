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


def require_module_access(module: str):
    def checker(user: User = Depends(get_current_user_required)) -> User:
        if user.role in ("admin", "superadmin"):
            return user
        if module == "adpulse" and user.access_adpulse:
            return user
        if module == "insightdesk" and user.access_insightdesk:
            return user
        if module == "revenueops" and user.access_revenueops:
            return user
        raise HTTPException(status_code=403, detail=f"Access denied to {module}")
    return checker


class UserUpdate(BaseModel):
    full_name: Optional[str] = None
    role: Optional[str] = None
    rev_role: Optional[str] = None
    mobile: Optional[str] = None
    is_active: Optional[bool] = None
    access_adpulse: Optional[bool] = None
    access_insightdesk: Optional[bool] = None
    access_revenueops: Optional[bool] = None


@router.put("/users/{user_id}")
def update_user(user_id: int, req: UserUpdate, db: Session = Depends(get_db), current_user: User = Depends(get_current_user_required)):
    if current_user.role not in ("admin", "superadmin"):
        raise HTTPException(status_code=403, detail="Only admin can update users")
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    if req.full_name is not None:
        user.full_name = req.full_name
    if req.role is not None:
        user.role = req.role
    if req.rev_role is not None:
        user.rev_role = req.rev_role
    if req.mobile is not None:
        user.mobile = req.mobile
    if req.is_active is not None:
        user.is_active = req.is_active
    if req.access_adpulse is not None:
        user.access_adpulse = req.access_adpulse
    if req.access_insightdesk is not None:
        user.access_insightdesk = req.access_insightdesk
    if req.access_revenueops is not None:
        user.access_revenueops = req.access_revenueops
    db.commit()
    db.refresh(user)
    return user.to_dict()


@router.get("/users")
def list_users(db: Session = Depends(get_db), current_user: User = Depends(get_current_user_required)):
    if current_user.role not in ("admin", "superadmin"):
        raise HTTPException(status_code=403, detail="Only admin can list users")
    users = db.query(User).all()
    return [u.to_dict() for u in users]


@router.delete("/users/{user_id}")
def delete_user(user_id: int, db: Session = Depends(get_db), current_user: User = Depends(get_current_user_required)):
    if current_user.role not in ("admin", "superadmin"):
        raise HTTPException(status_code=403, detail="Only admin can delete users")
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    db.delete(user)
    db.commit()
    return {"status": "success"}


@router.post("/seed-admin")
def seed_admin_user(password: str, db: Session = Depends(get_db)):
    """Convenience endpoint to create the first admin user. Disable or protect in production."""
    email = "admin@adoptima.ai"
    existing = db.query(User).filter(User.email == email).first()
    if existing:
        existing.role = "superadmin"
        existing.access_adpulse = True
        existing.access_insightdesk = True
        existing.access_revenueops = True
        db.commit()
        db.refresh(existing)
        return {"message": "Admin already exists, ensured superadmin access", "user": existing.to_dict()}
    user = User(
        email=email,
        hashed_password=get_password_hash(password),
        full_name="Admin",
        role="superadmin",
        access_adpulse=True,
        access_insightdesk=True,
        access_revenueops=True,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return {"message": "Admin created", "user": user.to_dict()}
