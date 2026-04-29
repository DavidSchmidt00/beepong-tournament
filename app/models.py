from datetime import datetime
from sqlalchemy import String, Integer, Enum, ForeignKey, DateTime, func
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.database import Base
import enum


class TournamentStatus(str, enum.Enum):
    setup = "setup"
    group_stage = "group_stage"
    knockout = "knockout"
    finished = "finished"


class MatchRound(str, enum.Enum):
    group = "group"
    semifinal = "semifinal"
    final = "final"
    third_place = "third_place"


class MatchStatus(str, enum.Enum):
    pending = "pending"
    completed = "completed"


class Tournament(Base):
    __tablename__ = "tournaments"

    id: Mapped[int] = mapped_column(primary_key=True)
    title: Mapped[str] = mapped_column(String(100), default="Beer Pong Turnier")
    status: Mapped[TournamentStatus] = mapped_column(default=TournamentStatus.setup)
    admin_password_hash: Mapped[str] = mapped_column(String(256))
    num_players: Mapped[int] = mapped_column(Integer, default=12)

    current_match_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    next_match_id: Mapped[int | None] = mapped_column(Integer, nullable=True)

    teams: Mapped[list["Team"]] = relationship(back_populates="tournament", cascade="all, delete-orphan")
    matches: Mapped[list["Match"]] = relationship(back_populates="tournament", cascade="all, delete-orphan")


class Team(Base):
    __tablename__ = "teams"

    id: Mapped[int] = mapped_column(primary_key=True)
    tournament_id: Mapped[int] = mapped_column(ForeignKey("tournaments.id"))
    name: Mapped[str] = mapped_column(String(50))
    emoji: Mapped[str] = mapped_column(String(10), default="🍺")
    player1: Mapped[str] = mapped_column(String(50))
    player2: Mapped[str] = mapped_column(String(50))
    group: Mapped[str] = mapped_column(String(1))  # "A" or "B"

    tournament: Mapped["Tournament"] = relationship(back_populates="teams")
    matches_as_a: Mapped[list["Match"]] = relationship(foreign_keys="Match.team_a_id", back_populates="team_a")
    matches_as_b: Mapped[list["Match"]] = relationship(foreign_keys="Match.team_b_id", back_populates="team_b")
    wins: Mapped[list["Match"]] = relationship(foreign_keys="Match.winner_id", back_populates="winner")


class Match(Base):
    __tablename__ = "matches"

    id: Mapped[int] = mapped_column(primary_key=True)
    tournament_id: Mapped[int] = mapped_column(ForeignKey("tournaments.id"))
    team_a_id: Mapped[int | None] = mapped_column(ForeignKey("teams.id"), nullable=True)
    team_b_id: Mapped[int | None] = mapped_column(ForeignKey("teams.id"), nullable=True)
    round: Mapped[MatchRound] = mapped_column()
    group: Mapped[str | None] = mapped_column(String(1), nullable=True)
    status: Mapped[MatchStatus] = mapped_column(default=MatchStatus.pending)
    winner_id: Mapped[int | None] = mapped_column(ForeignKey("teams.id"), nullable=True)
    cups_a: Mapped[int | None] = mapped_column(Integer, nullable=True)
    cups_b: Mapped[int | None] = mapped_column(Integer, nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    played_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    tournament: Mapped["Tournament"] = relationship(back_populates="matches")
    team_a: Mapped["Team | None"] = relationship(foreign_keys=[team_a_id], back_populates="matches_as_a")
    team_b: Mapped["Team | None"] = relationship(foreign_keys=[team_b_id], back_populates="matches_as_b")
    winner: Mapped["Team | None"] = relationship(foreign_keys=[winner_id], back_populates="wins")
