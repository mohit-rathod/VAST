"""VAST backend API."""

from contextlib import asynccontextmanager

from fastapi import FastAPI

from .chat import router as chat_router
from .config import VERSION
from .db import DB_PATH, init_db


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    yield


app = FastAPI(title="VAST API", version=VERSION, lifespan=lifespan)
app.include_router(chat_router)


@app.get("/health")
def health() -> dict:
    """Is the API up, which version is it, and which database is it using."""
    return {"status": "ok", "version": VERSION, "db": str(DB_PATH)}
