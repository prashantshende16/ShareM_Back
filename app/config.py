import os
from typing import List
from pydantic_settings import BaseSettings

class Settings(BaseSettings):
    PROJECT_NAME: str = "F&O Market Screenshot Analysis API"
    API_V1_PREFIX: str = "/api/v1"
    
    # Database
    DATABASE_URL: str = os.getenv("DATABASE_URL", "sqlite:///./fo_analyzer.db")
    
    # Uploads
    UPLOAD_DIR: str = os.getenv("UPLOAD_DIR", "uploads")
    MAX_FILE_SIZE_MB: int = 15
    ALLOWED_EXTENSIONS: List[str] = ["png", "jpg", "jpeg", "webp"]
    
    # AI Vision Provider Configuration
    AI_PROVIDER: str = os.getenv("AI_PROVIDER", "mock")  # openai, gemini, claude, mock
    
    OPENAI_API_KEY: str = os.getenv("OPENAI_API_KEY", "")
    OPENAI_MODEL: str = os.getenv("OPENAI_MODEL", "gpt-4o")
    
    GEMINI_API_KEY: str = os.getenv("GEMINI_API_KEY", "")
    GEMINI_MODEL: str = os.getenv("GEMINI_MODEL", "gemini-3.8-flash")
    
    ANTHROPIC_API_KEY: str = os.getenv("ANTHROPIC_API_KEY", "")
    ANTHROPIC_MODEL: str = os.getenv("ANTHROPIC_MODEL", "claude-3-5-sonnet-20241022")
    
    # Market Data Provider & Broker Integrations
    MARKET_DATA_PROVIDER: str = os.getenv("MARKET_DATA_PROVIDER", "none")
    DATA_SOURCE_PREFERENCE: str = os.getenv("DATA_SOURCE_PREFERENCE", "auto")  # auto, angel_one, yfinance
    
    # Angel One SmartAPI (100% Free Live Data & Option Chain)
    ANGEL_ONE_API_KEY: str = os.getenv("ANGEL_ONE_API_KEY", "")
    ANGEL_ONE_CLIENT_CODE: str = os.getenv("ANGEL_ONE_CLIENT_CODE", "")
    ANGEL_ONE_PIN: str = os.getenv("ANGEL_ONE_PIN", "")
    ANGEL_ONE_TOTP_KEY: str = os.getenv("ANGEL_ONE_TOTP_KEY", "")
    
    # CORS
    CORS_ORIGINS: List[str] = ["*"]

    class Config:
        env_file = ".env"
        extra = "allow"

settings = Settings()
