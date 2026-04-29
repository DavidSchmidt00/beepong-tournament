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
    """Recreate teams table without NOT NULL on player1/player2, if needed."""
    import sqlalchemy as sa
    with engine.connect() as conn:
        rows = conn.execute(sa.text("PRAGMA table_info(teams)")).fetchall()
        player1_row = next((r for r in rows if r[1] == "player1"), None)
        if player1_row is None or player1_row[3] == 0:
            return  # already nullable or doesn't exist

        conn.execute(sa.text("PRAGMA foreign_keys=OFF"))
        conn.execute(sa.text("""
            CREATE TABLE IF NOT EXISTS teams_new (
                id INTEGER NOT NULL PRIMARY KEY,
                tournament_id INTEGER REFERENCES tournaments(id),
                name VARCHAR(50),
                emoji VARCHAR(10) DEFAULT '🍺',
                player1 VARCHAR(50),
                player2 VARCHAR(50),
                "group" VARCHAR(1)
            )
        """))
        conn.execute(sa.text("""
            INSERT INTO teams_new (id, tournament_id, name, emoji, player1, player2, "group")
            SELECT id, tournament_id, name, emoji, player1, player2, "group" FROM teams
        """))
        conn.execute(sa.text("DROP TABLE teams"))
        conn.execute(sa.text("ALTER TABLE teams_new RENAME TO teams"))
        conn.execute(sa.text("PRAGMA foreign_keys=ON"))
        conn.commit()
