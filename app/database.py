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

    _migrate_teams_nullable_players()


def _migrate_teams_nullable_players():
    """Drop NOT NULL constraint on player1/player2 in teams table, if still present."""
    import sqlalchemy as sa
    with engine.connect() as conn:
        row = conn.execute(sa.text("""
            SELECT is_nullable FROM information_schema.columns
            WHERE table_name = 'teams' AND column_name = 'player1'
        """)).fetchone()
        if row is None or row[0] == 'YES':
            return  # column already nullable or doesn't exist

        conn.execute(sa.text("ALTER TABLE teams ALTER COLUMN player1 DROP NOT NULL"))
        conn.execute(sa.text("ALTER TABLE teams ALTER COLUMN player2 DROP NOT NULL"))
        conn.commit()
