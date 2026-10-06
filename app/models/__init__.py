from datetime import datetime
import json
from sqlalchemy import Column, Integer, String, Float, Text, DateTime, ForeignKey, Boolean
from sqlalchemy.orm import relationship
from app.database import Base

class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(100), nullable=False)
    email = Column(String(255), unique=True, index=True, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    analyses = relationship("Analysis", back_populates="user", cascade="all, delete-orphan")


class Analysis(Base):
    __tablename__ = "analyses"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    market = Column(String(50), nullable=False, default="NIFTY")
    instrument = Column(String(100), nullable=True)
    instrument_type = Column(String(50), nullable=False, default="Index")
    symbol = Column(String(50), nullable=False, default="NIFTY 50")
    expiry = Column(String(50), nullable=True)
    strike_price = Column(Float, nullable=True)
    option_type = Column(String(20), nullable=True, default="N/A")
    
    current_price = Column(Float, nullable=True)
    previous_close = Column(Float, nullable=True)
    day_high = Column(Float, nullable=True)
    day_low = Column(Float, nullable=True)
    volume = Column(String(50), nullable=True)
    open_interest = Column(String(50), nullable=True)
    pcr = Column(Float, nullable=True)
    india_vix = Column(Float, nullable=True)
    notes = Column(Text, nullable=True)
    
    status = Column(String(30), default="pending")  # pending, analyzing, completed, failed
    error_message = Column(Text, nullable=True)

    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Relationships
    user = relationship("User", back_populates="analyses")
    screenshots = relationship("AnalysisScreenshot", back_populates="analysis", cascade="all, delete-orphan")
    result = relationship("AnalysisResult", back_populates="analysis", uselist=False, cascade="all, delete-orphan")
    scenarios = relationship("ScenarioPrediction", back_populates="analysis", cascade="all, delete-orphan")


class AnalysisScreenshot(Base):
    __tablename__ = "analysis_screenshots"

    id = Column(Integer, primary_key=True, index=True)
    analysis_id = Column(Integer, ForeignKey("analyses.id", ondelete="CASCADE"), nullable=False)
    timeframe = Column(String(50), nullable=False, default="15 Minute")
    file_path = Column(String(500), nullable=False)
    file_name = Column(String(255), nullable=False)
    mime_type = Column(String(100), nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)

    analysis = relationship("Analysis", back_populates="screenshots")


class AnalysisResult(Base):
    __tablename__ = "analysis_results"

    id = Column(Integer, primary_key=True, index=True)
    analysis_id = Column(Integer, ForeignKey("analyses.id", ondelete="CASCADE"), nullable=False, unique=True)
    
    trend = Column(String(50), default="Neutral")
    primary_scenario = Column(String(50), default="sideways")  # bullish, bearish, sideways
    confidence_score = Column(Integer, default=50)
    
    market_structure = Column(Text, default="{}")  # JSON encoded
    support_levels = Column(Text, default="[]")  # JSON encoded
    resistance_levels = Column(Text, default="[]")  # JSON encoded
    candlestick_analysis = Column(Text, default="{}")  # JSON encoded
    volume_analysis = Column(Text, default="{}")  # JSON encoded
    oi_analysis = Column(Text, default="{}")  # JSON encoded
    technical_indicators = Column(Text, default="{}")  # JSON encoded
    
    bullish_scenario = Column(Text, default="{}")  # JSON encoded
    bearish_scenario = Column(Text, default="{}")  # JSON encoded
    sideways_scenario = Column(Text, default="{}")  # JSON encoded
    
    risk_analysis = Column(Text, default="{}")  # JSON encoded
    trade_setup = Column(Text, default="{}")  # JSON encoded (setup direction, entry, sl, targets, rr)
    time_movements = Column(Text, default="[]")  # JSON encoded (5-15m, 15-30m, 30-60m, 1-2h)
    multi_timeframe_synthesis = Column(Text, default="{}")  # JSON encoded multi-TF breakdown
    detected_overlays = Column(Text, default="[]")  # Bounding box / price line annotations for image viewer
    
    entry_zone = Column(String(100), nullable=True)
    stop_loss_zone = Column(String(100), nullable=True)
    target_zone = Column(String(100), nullable=True)
    confirmation_conditions = Column(Text, default="[]")  # JSON encoded
    invalidating_conditions = Column(Text, default="[]")  # JSON encoded
    time_horizon = Column(String(100), default="15-60 Minutes")
    ai_summary = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    analysis = relationship("Analysis", back_populates="result")


class ScenarioPrediction(Base):
    __tablename__ = "scenario_predictions"

    id = Column(Integer, primary_key=True, index=True)
    analysis_id = Column(Integer, ForeignKey("analyses.id", ondelete="CASCADE"), nullable=False)
    scenario_type = Column(String(50), nullable=False)  # bullish, bearish, sideways
    probability = Column(Integer, nullable=False, default=33)
    expected_direction = Column(String(100), nullable=True)
    expected_range = Column(String(100), nullable=True)
    timeframe = Column(String(100), nullable=True)
    trigger_condition = Column(Text, nullable=True)
    invalidation_condition = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    analysis = relationship("Analysis", back_populates="scenarios")


class WatchlistItem(Base):
    __tablename__ = "watchlist_items"

    id = Column(Integer, primary_key=True, index=True)
    symbol = Column(String(50), nullable=False, unique=True)
    market = Column(String(50), nullable=False, default="NSE")
    last_analysis_id = Column(Integer, ForeignKey("analyses.id", ondelete="SET NULL"), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    last_analysis = relationship("Analysis")
