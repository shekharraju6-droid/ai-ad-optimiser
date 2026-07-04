"""
Dynamic category management endpoints for Client/Brand forms.
"""
import logging
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session
from backend.db.database import get_db
from backend.db.models import Category, Account
from backend.routes.auth import get_current_user_required

logger = logging.getLogger("AdOptima")
router = APIRouter(prefix="/api", tags=["categories"])


class CategoryCreate(BaseModel):
    name: str


class CategoryUpdate(BaseModel):
    name: str


@router.get("/categories")
def list_categories(db: Session = Depends(get_db), user=Depends(get_current_user_required)):
    """Return all categories sorted alphabetically."""
    categories = db.query(Category).order_by(Category.name.asc()).all()
    return {"categories": [{"id": c.id, "name": c.name} for c in categories]}


@router.post("/categories")
def create_category(req: CategoryCreate, db: Session = Depends(get_db), user=Depends(get_current_user_required)):
    """Create a new category."""
    name = (req.name or "").strip()
    if not name:
        raise HTTPException(status_code=400, detail="Category name cannot be empty")
    existing = db.query(Category).filter(Category.name.ilike(name)).first()
    if existing:
        raise HTTPException(status_code=400, detail="Category already exists")
    category = Category(name=name)
    db.add(category)
    db.commit()
    db.refresh(category)
    return {"id": category.id, "name": category.name}


@router.put("/categories/{category_id}")
def update_category(category_id: int, req: CategoryUpdate, db: Session = Depends(get_db), user=Depends(get_current_user_required)):
    """Update category name."""
    category = db.query(Category).filter(Category.id == category_id).first()
    if not category:
        raise HTTPException(status_code=404, detail="Category not found")
    name = (req.name or "").strip()
    if not name:
        raise HTTPException(status_code=400, detail="Category name cannot be empty")
    duplicate = db.query(Category).filter(Category.name.ilike(name), Category.id != category_id).first()
    if duplicate:
        raise HTTPException(status_code=400, detail="Category name already exists")
    category.name = name
    db.commit()
    db.refresh(category)
    return {"id": category.id, "name": category.name}


@router.delete("/categories/{category_id}")
def delete_category(category_id: int, db: Session = Depends(get_db), user=Depends(get_current_user_required)):
    """Delete category only if no accounts reference it."""
    category = db.query(Category).filter(Category.id == category_id).first()
    if not category:
        raise HTTPException(status_code=404, detail="Category not found")
    count = db.query(Account).filter(Account.category_id == category_id).count()
    if count > 0:
        raise HTTPException(
            status_code=400,
            detail=f"Cannot delete - {count} Client/Brand records use this category. Reassign them first."
        )
    db.delete(category)
    db.commit()
    return {"detail": "Category deleted"}
