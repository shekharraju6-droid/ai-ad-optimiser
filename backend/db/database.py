"""
Database setup using SQLAlchemy.
Supports SQLite (local dev) and PostgreSQL (Supabase/Railway).
"""
import os
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, declarative_base

DATABASE_URL = os.getenv("DATABASE_URL")

if DATABASE_URL:
    # Supabase / PostgreSQL
    engine = create_engine(DATABASE_URL)
else:
    # SQLite fallback (local dev)
    ROOT_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    DB_PATH = os.getenv("ADOPTIMA_DB_PATH", os.path.join(ROOT_DIR, "adoptima.db"))
    if os.path.dirname(DB_PATH):
        os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    else:
        DB_PATH = os.path.join(ROOT_DIR, DB_PATH)
        os.makedirs(ROOT_DIR, exist_ok=True)
    engine = create_engine(f"sqlite:///{DB_PATH}", connect_args={"check_same_thread": False})

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()


def get_raw_connection():
    """Return a DB-API style connection for raw SQL. Works for SQLite and PostgreSQL."""
    return engine.raw_connection()


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def init_db():
    import backend.db.models  # noqa: F401
    import backend.db.revenueops_models  # noqa: F401
    Base.metadata.create_all(bind=engine)
