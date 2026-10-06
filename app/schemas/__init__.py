from datetime import datetime
from typing import List, Optional, Dict, Any, Union
from pydantic import BaseModel, Field

# Screenshot Schemas
class ScreenshotBase(BaseModel):
    timeframe: str = "15 Minute"

class ScreenshotResponse(BaseModel):
    id: int
    analysis_id: int
    timeframe: str
    file_path: str
    file_name: str
    mime_type: str
    url: Optional[str] = None
    created_at: datetime

    class Config:
        from_attributes = True

# Scenario Schemas
class ScenarioDetail(BaseModel):
    type: str  # bullish, bearish, sideways
    probability: int = 0
    trigger: str = ""
    confirmation: str = ""
    potential_movement: str = ""
    expected_range: str = ""
    invalidation: str = ""
    time_horizon: str = "15-60 Minutes"
    risk_level: str = "Medium"

class TimeMovementItem(BaseModel):
    timeframe: str
    bias: str
    confidence: int
    condition: str
    expected_behavior: str
    invalidation: str

class MultiTimeframeItem(BaseModel):
    timeframe: str
    trend: str
    structure: str
    bias: str

class TradeSetup(BaseModel):
    has_setup: bool = True
    direction: str = "NO TRADE"  # CALL, PUT, FUTURE, NO TRADE
    entry_zone: Optional[str] = "N/A"
    stop_loss: Optional[str] = "N/A"
    target_1: Optional[str] = "N/A"
    target_2: Optional[str] = "N/A"
    risk_reward: Optional[str] = "N/A"
    reason: Optional[str] = None

class RiskAnalysis(BaseModel):
    risk_level: str = "MEDIUM"  # LOW, MEDIUM, HIGH
    setup_quality: str = "B"     # A, B, C
    reward_risk: str = "1:2.0"
    invalidation: str = "Key level breach"
    main_risk: str = "False breakout / whip-saw"
    disclaimer: str = (
        "This analysis is probabilistic and educational. It is not financial advice. "
        "Market conditions can change rapidly. Always independently verify levels and manage risk."
    )

class OverlayAnnotation(BaseModel):
    id: str
    type: str  # support, resistance, breakout, breakdown, pattern
    label: str
    price: Optional[float] = None
    y_percent: Optional[float] = None  # 0 to 100 on chart
    box: Optional[Dict[str, float]] = None  # {x, y, width, height} in percentages

# Result Schemas
class AnalysisResultResponse(BaseModel):
    id: int
    analysis_id: int
    trend: str
    primary_scenario: str
    confidence_score: int
    market_structure: Dict[str, Any] = {}
    support_levels: List[Dict[str, Any]] = []
    resistance_levels: List[Dict[str, Any]] = []
    candlestick_analysis: Dict[str, Any] = {}
    volume_analysis: Dict[str, Any] = {}
    oi_analysis: Dict[str, Any] = {}
    technical_indicators: Dict[str, Any] = {}
    bullish_scenario: Dict[str, Any] = {}
    bearish_scenario: Dict[str, Any] = {}
    sideways_scenario: Dict[str, Any] = {}
    risk_analysis: Dict[str, Any] = {}
    trade_setup: Dict[str, Any] = {}
    time_movements: List[Dict[str, Any]] = []
    multi_timeframe_synthesis: Dict[str, Any] = {}
    detected_overlays: List[Dict[str, Any]] = []
    entry_zone: Optional[str] = None
    stop_loss_zone: Optional[str] = None
    target_zone: Optional[str] = None
    confirmation_conditions: List[str] = []
    invalidating_conditions: List[str] = []
    time_horizon: str = "15-60 Minutes"
    ai_summary: Optional[str] = None
    created_at: datetime

    class Config:
        from_attributes = True

# Analysis Request / Response
class AnalysisCreate(BaseModel):
    market: str = "NIFTY"
    instrument: Optional[str] = None
    instrument_type: str = "Index"
    symbol: str = "NIFTY 50"
    expiry: Optional[str] = None
    strike_price: Optional[float] = None
    option_type: Optional[str] = "N/A"
    current_price: Optional[float] = None
    previous_close: Optional[float] = None
    day_high: Optional[float] = None
    day_low: Optional[float] = None
    volume: Optional[str] = None
    open_interest: Optional[str] = None
    pcr: Optional[float] = None
    india_vix: Optional[float] = None
    notes: Optional[str] = None

class AnalysisUpdate(BaseModel):
    market: Optional[str] = None
    symbol: Optional[str] = None
    notes: Optional[str] = None
    current_price: Optional[float] = None

class ScenarioPredictionResponse(BaseModel):
    id: int
    scenario_type: str
    probability: int
    expected_direction: Optional[str] = None
    expected_range: Optional[str] = None
    timeframe: Optional[str] = None
    trigger_condition: Optional[str] = None
    invalidation_condition: Optional[str] = None

    class Config:
        from_attributes = True

class AnalysisResponse(BaseModel):
    id: int
    user_id: Optional[int] = None
    market: str
    instrument: Optional[str] = None
    instrument_type: str
    symbol: str
    expiry: Optional[str] = None
    strike_price: Optional[float] = None
    option_type: Optional[str] = None
    current_price: Optional[float] = None
    previous_close: Optional[float] = None
    day_high: Optional[float] = None
    day_low: Optional[float] = None
    volume: Optional[str] = None
    open_interest: Optional[str] = None
    pcr: Optional[float] = None
    india_vix: Optional[float] = None
    notes: Optional[str] = None
    status: str
    error_message: Optional[str] = None
    created_at: datetime
    updated_at: datetime
    screenshots: List[ScreenshotResponse] = []
    result: Optional[AnalysisResultResponse] = None
    scenarios: List[ScenarioPredictionResponse] = []

    class Config:
        from_attributes = True

# Dashboard Stats
class DashboardStats(BaseModel):
    total_analyses: int
    bullish_scenarios: int
    bearish_scenarios: int
    sideways_scenarios: int
    high_confidence_analyses: int

# Watchlist Schemas
class WatchlistItemCreate(BaseModel):
    symbol: str
    market: str = "NSE"

class WatchlistItemResponse(BaseModel):
    id: int
    symbol: str
    market: str
    last_analysis_id: Optional[int] = None
    last_bias: Optional[str] = "N/A"
    last_confidence: Optional[int] = None
    last_timeframe: Optional[str] = None
    last_updated: Optional[datetime] = None

    class Config:
        from_attributes = True

# Compare Schemas
class CompareResponse(BaseModel):
    analysis_1: AnalysisResponse
    analysis_2: AnalysisResponse
    diff: Dict[str, Any]

# Settings Schemas
class SettingsUpdate(BaseModel):
    ai_provider: Optional[str] = None
    openai_api_key: Optional[str] = None
    gemini_api_key: Optional[str] = None
    anthropic_api_key: Optional[str] = None
    openai_model: Optional[str] = None
    gemini_model: Optional[str] = None
    anthropic_model: Optional[str] = None

class SettingsStatusResponse(BaseModel):
    current_provider: str
    available_providers: List[str]
    is_openai_configured: bool
    is_gemini_configured: bool
    is_anthropic_configured: bool
    market_data_connected: bool
    market_data_status: str
