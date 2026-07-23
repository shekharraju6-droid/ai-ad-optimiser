"""
Migration: Create mis_projects and mis_daily_snapshots tables and seed
Mantri -> Serenity project if not present.
"""
import logging
from sqlalchemy import inspect, text
from sqlalchemy.orm import Session
from backend.db.database import Base, engine, get_active_db
from backend.db.models import Account

logger = logging.getLogger("AdOptima")


def run_migration():
    db = Session(bind=engine)
    try:
        active_db = get_active_db()
        inspector = inspect(engine)
        tables = inspector.get_table_names()

        if "mis_projects" not in tables:
            logger.info("Creating mis_projects table")
            if active_db == "sqlite":
                db.execute(text("""
                    CREATE TABLE mis_projects (
                        id INTEGER NOT NULL PRIMARY KEY AUTOINCREMENT,
                        client_id INTEGER NOT NULL REFERENCES accounts(id),
                        name VARCHAR NOT NULL,
                        is_active BOOLEAN DEFAULT 1,
                        created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                        updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
                    )
                """))
            else:
                db.execute(text("""
                    CREATE TABLE mis_projects (
                        id SERIAL PRIMARY KEY,
                        client_id INTEGER NOT NULL REFERENCES accounts(id),
                        name VARCHAR NOT NULL,
                        is_active BOOLEAN DEFAULT TRUE,
                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                    )
                """))
            db.commit()
        else:
            logger.info("mis_projects table already exists")

        if "mis_daily_snapshots" not in tables:
            logger.info("Creating mis_daily_snapshots table")
            if active_db == "sqlite":
                db.execute(text("""
                    CREATE TABLE mis_daily_snapshots (
                        id INTEGER NOT NULL PRIMARY KEY AUTOINCREMENT,
                        project_id INTEGER NOT NULL REFERENCES mis_projects(id),
                        platform VARCHAR NOT NULL,
                        date DATE NOT NULL,
                        leads FLOAT DEFAULT 0.0,
                        amount_spent FLOAT DEFAULT 0.0,
                        cpl FLOAT,
                        created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                        updated_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                        UNIQUE (project_id, platform, date)
                    )
                """))
            else:
                # PostgreSQL: use partial unique index that ignores soft-deleted projects if any,
                # or plain unique constraint. We use plain unique constraint per spec.
                db.execute(text("""
                    CREATE TABLE mis_daily_snapshots (
                        id SERIAL PRIMARY KEY,
                        project_id INTEGER NOT NULL REFERENCES mis_projects(id),
                        platform VARCHAR NOT NULL,
                        date DATE NOT NULL,
                        leads FLOAT DEFAULT 0.0,
                        amount_spent FLOAT DEFAULT 0.0,
                        cpl FLOAT,
                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                        CONSTRAINT uix_snapshot UNIQUE (project_id, platform, date)
                    )
                """))
            db.commit()
        else:
            logger.info("mis_daily_snapshots table already exists")

        # Seed Mantri -> Serenity project
        Base.metadata.reflect(bind=engine)
        mantri = db.query(Account).filter(Account.name.ilike("%mantri%")).first()
        if mantri:
            existing = db.execute(
                text("SELECT id FROM mis_projects WHERE client_id = :client_id AND name = 'Serenity'"),
                {"client_id": mantri.id},
            ).fetchone()
            if not existing:
                logger.info(f"Seeding MIS project Serenity for client {mantri.id}")
                db.execute(
                    text("INSERT INTO mis_projects (client_id, name, is_active) VALUES (:client_id, 'Serenity', TRUE)"),
                    {"client_id": mantri.id},
                )
                db.commit()
            else:
                logger.info("Mantri Serenity MIS project already seeded")
        else:
            logger.warning("Mantri account not found; skipping MIS project seed")

        logger.info("MIS project migration complete")
    except Exception as e:
        db.rollback()
        logger.error(f"MIS project migration failed: {e}")
        raise
    finally:
        db.close()


if __name__ == "__main__":
    run_migration()
