
from fastapi import Depends, FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.database import get_db
from app.routers import routes as auth
from app.routers import movies
from app.routers import admin
from app.routers import sharing


app = FastAPI(
    title="MovieShare API",
    description="Secure Movie Sharing Platform",
    version="1.0.0",
)


app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173",
        "http://127.0.0.1:5173",
        "http://localhost:5174",
        "http://127.0.0.1:5174",
        "https://movieshare.onrender.com",
    ],
    allow_credentials=False,
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type"],
)


# Authentication endpoints
app.include_router(auth.router)

# Movie endpoints
app.include_router(movies.router)

# Admin endpoints
app.include_router(admin.router)

# Movie sharing endpoints
app.include_router(sharing.router)


@app.get("/")
def home():
    return {
        "message": "MovieShare backend is running!"
    }


@app.get("/health")
def health_check(db: Session = Depends(get_db)):
    try:
        db.execute(text("SELECT 1"))

        return {
            "status": "healthy",
            "database": "connected",
        }

    except Exception:
        raise HTTPException(
            status_code=503,
            detail="Database connection failed",
        )

