# app/main.py - minimal stub for tests; full implementation comes in Task 4
import os
from contextlib import asynccontextmanager
from fastapi import FastAPI, Depends
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session

from app.database import get_db, init_db
from app.models import Tournament, TournamentStatus


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    yield


app = FastAPI(lifespan=lifespan)


@app.get("/")
def root(db: Session = Depends(get_db)):
    tournament = db.query(Tournament).first()
    if not tournament or tournament.status == TournamentStatus.setup:
        return RedirectResponse(url="/setup")
    return RedirectResponse(url="/admin")
