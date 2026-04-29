import os
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, DeclarativeBase

DATABASE_URL = os.environ["DATABASE_URL"]

engine = create_engine(DATABASE_URL)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


class Base(DeclarativeBase):
    pass


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def init_db():
    from app import models  # noqa: F401 — ensures models are registered
    Base.metadata.create_all(bind=engine)
    _run_migrations()


def _run_migrations():
    migrations = [
        "ALTER TABLE teams ADD COLUMN IF NOT EXISTS emoji VARCHAR(10) DEFAULT '🍺'",
        "ALTER TABLE tournaments ADD COLUMN IF NOT EXISTS current_match_id INTEGER",
        "ALTER TABLE tournaments ADD COLUMN IF NOT EXISTS next_match_id INTEGER",
        "ALTER TABLE matches ADD COLUMN IF NOT EXISTS started_at TIMESTAMP",
    ]
    with engine.connect() as conn:
        for sql in migrations:
            conn.execute(__import__("sqlalchemy").text(sql))
        conn.commit()
