"""
Migration: Create categories table, add accounts.category_id, and migrate
existing account group names into categories so existing Client/Brand records
keep their current category values.
"""
import logging
from sqlalchemy import Column, Integer, String, DateTime, ForeignKey, inspect, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from backend.db.database import Base, engine, get_active_db
from backend.db.models import Account, AccountGroup, Category

logger = logging.getLogger("AdOptima")


def run_migration():
    db = Session(bind=engine)
    try:
        active_db = get_active_db()
        inspector = inspect(engine)

        # Create categories table if it doesn't exist
        if "categories" not in inspector.get_table_names():
            logger.info("Creating categories table")
            if active_db == "sqlite":
                db.execute(text("""
                    CREATE TABLE categories (
                        id INTEGER NOT NULL PRIMARY KEY AUTOINCREMENT,
                        name VARCHAR NOT NULL UNIQUE,
                        created_at DATETIME DEFAULT CURRENT_TIMESTAMP
                    )
                """))
            else:
                db.execute(text("""
                    CREATE TABLE categories (
                        id SERIAL PRIMARY KEY,
                        name VARCHAR NOT NULL UNIQUE,
                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                    )
                """))
            db.commit()
        else:
            logger.info("categories table already exists")

        # Add accounts.category_id if missing
        account_columns = {c["name"] for c in inspector.get_columns("accounts")}
        if "category_id" not in account_columns:
            logger.info("Adding accounts.category_id column")
            db.execute(text("ALTER TABLE accounts ADD COLUMN category_id INTEGER REFERENCES categories(id)"))
            db.commit()
        else:
            logger.info("accounts.category_id already present")

        # Refresh ORM mapper so Category table is usable
        Base.metadata.reflect(bind=engine)

        # Seed default categories if none exist
        default_categories = [
            "Education",
            "Healthcare",
            "Real Estate",
            "Retail",
            "Technology",
            "Manufacturing",
            "Hospitality",
            "Others",
        ]
        existing_names = {c.name for c in db.query(Category).all()}
        for name in default_categories:
            if name not in existing_names:
                try:
                    db.add(Category(name=name))
                    db.commit()
                    existing_names.add(name)
                except IntegrityError:
                    db.rollback()

        # Migrate existing account group names into categories and link accounts
        groups = db.query(AccountGroup).all()
        group_name_to_category_id = {}
        for group in groups:
            cat = db.query(Category).filter(Category.name == group.name).first()
            if not cat:
                cat = Category(name=group.name)
                db.add(cat)
                try:
                    db.commit()
                except IntegrityError:
                    db.rollback()
                    cat = db.query(Category).filter(Category.name == group.name).first()
            group_name_to_category_id[group.id] = cat.id if cat else None

        # Assign category_id to accounts based on their existing group_id
        for account in db.query(Account).filter(Account.group_id.isnot(None)).all():
            if account.group_id in group_name_to_category_id:
                account.category_id = group_name_to_category_id[account.group_id]
        db.commit()

        logger.info("Category migration complete")
    except Exception as e:
        db.rollback()
        logger.error(f"Category migration failed: {e}")
        raise
    finally:
        db.close()


if __name__ == "__main__":
    run_migration()
