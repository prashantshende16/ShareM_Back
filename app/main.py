import os
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from app.config import settings
from app.database import engine, Base
from app import models
from app.routers import analyses, screenshots, watchlist, settings as settings_router, market
from app.utils.file_upload import ensure_upload_dir

# Ensure database tables exist
Base.metadata.create_all(bind=engine)

# Ensure upload directory exists
ensure_upload_dir()

app = FastAPI(
    title=settings.PROJECT_NAME,
    version="1.0.0",
    description="Full-stack AI-assisted Futures & Options Market Screenshot Analysis API"
)

# CORS configuration
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Static files for uploaded screenshots
app.mount("/uploads", StaticFiles(directory=settings.UPLOAD_DIR), name="uploads")

# Include Routers
app.include_router(analyses.router, prefix=settings.API_V1_PREFIX)
app.include_router(screenshots.router, prefix=settings.API_V1_PREFIX)
app.include_router(watchlist.router, prefix=settings.API_V1_PREFIX)
app.include_router(settings_router.router, prefix=settings.API_V1_PREFIX)
app.include_router(market.router, prefix=settings.API_V1_PREFIX)

@app.get("/health")
@app.get(f"{settings.API_V1_PREFIX}/health")
def health_check():
    return {
        "status": "healthy",
        "service": settings.PROJECT_NAME,
        "ai_provider": settings.AI_PROVIDER,
        "database": "connected"
    }

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("app.main:app", host="0.0.0.0", port=8000, reload=True)
