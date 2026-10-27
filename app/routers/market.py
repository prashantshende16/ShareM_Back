import os
import uuid
import logging
from datetime import datetime, timedelta
import pytz
from concurrent.futures import ThreadPoolExecutor
from typing import Optional, List, Dict, Any
from fastapi import APIRouter, Depends, HTTPException, Query, BackgroundTasks
from sqlalchemy.orm import Session
from pydantic import BaseModel

from app.database import get_db
from app.models import Analysis, AnalysisScreenshot
from app.services.market_data.live_market_service import LiveMarketService
from app.services.chart_analysis.chart_analyzer import ChartAnalyzer

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/market", tags=["Live Market"])

class LiveAnalysisRequest(BaseModel):
    symbol: str = "NIFTY 50"
    market: str = "NIFTY"
    instrument_type: str = "Index"
    notes: Optional[str] = None
    ai_provider: Optional[str] = None

class AIStrategyAgentRequest(BaseModel):
    symbol: str = "NIFTY 50"
    expiry_type: str = "current"
    timeframe: str = "5m"

@router.get("/global-radar")
def get_global_market_radar():
    """
    Returns comprehensive Global Market Radar tracking US, UK/Europe, Asia,
    Commodities (Crude Oil, Gold), USD/INR, and live news tally at current timing.
    """
    radar = LiveMarketService.get_global_market_radar()
    return {
        "status": "success",
        "data": radar
    }

@router.get("/surge-radar")
def get_surge_radar(force: bool = False):
    """
    Automated Sudden Movement & Momentum Surge Radar:
    Detects 10% - 20%+ rapid option price expansions, volume surges,
    and calculates Delta with live Nasdaq, Dow Jones, and India VIX observations.
    Generates automated actionable CALL and PUT trade suggestions.
    """
    from app.services.technical_analysis.surge_radar_service import SurgeRadarService
    return SurgeRadarService.scan_surge_radar(force_refresh=force)

@router.post("/surge-radar/reset-notifications")
def reset_surge_radar_notifications():
    """
    Marks all sudden surge alerts as viewed / read.
    """
    from app.services.technical_analysis.surge_radar_service import SurgeRadarService
    return SurgeRadarService.reset_notifications()

@router.post("/ai-strategy-agent")
async def run_ai_market_strategy_agent(payload: AIStrategyAgentRequest):
    """
    AI Live Market Strategy Agent:
    Blends Angel One SmartAPI live quotes + 5m/15m multi-indicator technicals +
    US/UK/European market movements + real-time breaking news through Google Gemini AI.
    """
    from app.services.ai.market_strategy_agent import AIMarketStrategyAgent
    result = await AIMarketStrategyAgent.synthesize_market_strategy(
        symbol=payload.symbol,
        expiry_type=payload.expiry_type,
        timeframe=payload.timeframe
    )
    return result

@router.get("/overview")
def get_live_overview():
    """
    Returns live global sentiment, world indices, heavyweight contributors, and macro market incidents.
    """
    global_data = LiveMarketService.get_global_market_overview()
    heavyweights = LiveMarketService.get_heavyweights_overview()
    news = LiveMarketService.get_market_incidents_news()

    return {
        "status": "success",
        "global_sentiment": global_data.get("global_sentiment"),
        "indices": global_data.get("indices", []),
        "heavyweights": heavyweights,
        "recent_incidents": news
    }

@router.get("/timeframes")
def get_live_timeframes(symbol: str = Query(default="NIFTY 50")):
    """
    Returns live multi-timeframe candle and technical data (1m, 5m, 15m, 30m, 1h).
    """
    data = LiveMarketService.get_multi_timeframe_data(symbol)
    return {
        "status": "success",
        "symbol": symbol,
        "data": data
    }

@router.get("/option-signal")
def get_option_indicator_signal(
    symbol: str = Query(default="NIFTY 50"),
    expiry_type: str = Query(default="current", description="Expiry preference: 'current' or 'next'"),
    strike: Optional[int] = Query(default=None, description="Specific strike to evaluate"),
    option_type: Optional[str] = Query(default=None, description="Option type: 'CE' or 'PE'"),
    timeframe: str = Query(default="5m", description="Candle timeframe: '5m' or '15m'"),
    lot_size: Optional[int] = Query(default=None, description="Custom lot size override (e.g. 20 for Sensex, 60 for Bank Nifty)")
):
    """
    Dedicated 5-Minute and 15-Minute Option Indicator Decision Endpoint.
    Evaluates 5m or 15m candles with:
    - Candlestick patterns (Hammer, Shooting Star, Engulfing, Morning/Evening Star, Pinbars)
    - EMA 9/21 Ribbon & EMA 50/200 Long-Term Trend
    - RSI 14 Momentum
    - Intraday VWAP Alignment
    - MACD (12, 26, 9) Histogram & Crossover
    - Bollinger Bands (20, 2) Squeeze & Position
    - Central Pivot Range (CPR) & Classic Levels
    - Volume Spikes & Institutional Filter
    - Real-Time Live Option Chain Quotes from Angel One SmartAPI
    Returns definitive BUY CALL (CE) / BUY PUT (PE) / WAIT decision, strike recommendation, SL & Targets.
    """
    from app.services.technical_analysis.option_indicator import OptionSignalIndicator

    yf_sym = LiveMarketService.resolve_symbol(symbol)
    tf_clean = str(timeframe or "5m").strip().lower()
    if tf_clean in ["1h", "60m", "60", "1 hour"]:
        interval = "1h"
    elif tf_clean in ["30m", "30", "30min", "30 minute"]:
        interval = "30m"
    elif tf_clean in ["15m", "15", "15min", "15 minute"]:
        interval = "15m"
    else:
        interval = "5m"

    data = LiveMarketService.get_candle_data(yf_sym, interval=interval, range_="5d")
    if not data or not data.get("candles"):
        data = LiveMarketService.get_candle_data(yf_sym, interval=interval, range_="1d")

    candles = data.get("candles", []) if data else []
    cmp = data.get("current_price") if data else None
    signal = OptionSignalIndicator.evaluate_5m_option_signal(
        candles,
        cmp,
        symbol=symbol,
        expiry_type=expiry_type,
        selected_strike=strike,
        selected_option_type=option_type,
        timeframe=timeframe,
        custom_lot_size=lot_size
    )

    return {
        "status": "success",
        "symbol": symbol,
        "yf_symbol": yf_sym,
        "expiry_type": expiry_type,
        "timeframe": timeframe,
        "signal": signal
    }

@router.get("/all-option-signals")
def get_all_option_indicator_signals(
    expiry_type: str = Query(default="current", description="Expiry preference: 'current' or 'next'"),
    timeframe: str = Query(default="5m", description="Candle timeframe: '5m' or '15m'")
):
    """
    Evaluates 5-Minute or 15-Minute Option Indicator Decisions for ALL Major Indian Indices in parallel:
    - NIFTY 50
    - BANK NIFTY
    - SENSEX
    - FINNIFTY
    - MIDCPNIFTY
    Recalculates all signals starting from the exact refresh time onward.
    """
    from app.services.technical_analysis.option_indicator import OptionSignalIndicator

    symbols = ["NIFTY 50", "BANK NIFTY", "SENSEX", "FINNIFTY", "MIDCPNIFTY"]
    results = {}
    tf_clean = str(timeframe or "5m").strip().lower()
    if tf_clean in ["1h", "60m", "60", "1 hour"]:
        interval = "1h"
        valid_mins = 120
        tf_display = "1 Hour"
    elif tf_clean in ["30m", "30", "30min", "30 minute"]:
        interval = "30m"
        valid_mins = 60
        tf_display = "30 Minute"
    elif tf_clean in ["15m", "15", "15min", "15 minute"]:
        interval = "15m"
        valid_mins = 45
        tf_display = "15 Minute"
    else:
        interval = "5m"
        valid_mins = 30
        tf_display = "5 Minute"

    def process_sym(sym):
        try:
            yf_sym = LiveMarketService.resolve_symbol(sym)
            data = LiveMarketService.get_candle_data(yf_sym, interval=interval, range_="5d")
            if not data or not data.get("candles"):
                data = LiveMarketService.get_candle_data(yf_sym, interval=interval, range_="1d")
            candles = data.get("candles", []) if data else []
            cmp = data.get("current_price") if data else None
            sig = OptionSignalIndicator.evaluate_5m_option_signal(
                candles, cmp, symbol=sym, expiry_type=expiry_type, timeframe=timeframe
            )
            return sym, sig
        except Exception as e:
            logger.warning(f"Error evaluating all-market signal for {sym}: {e}")
            return sym, None

    with ThreadPoolExecutor(max_workers=5) as executor:
        futures = [executor.submit(process_sym, s) for s in symbols]
        for f in futures:
            s_name, s_res = f.result()
            if s_res:
                results[s_name] = s_res

    ist = pytz.timezone("Asia/Kolkata")
    now_ist = datetime.now(ist)

    return {
        "status": "success",
        "timestamp": now_ist.strftime("%I:%M:%S %p"),
        "timestamp_iso": now_ist.isoformat(),
        "valid_until": (now_ist + timedelta(minutes=valid_mins)).strftime("%I:%M:%S %p"),
        "timeframe": tf_display,
        "total_markets": len(results),
        "signals": results
    }

@router.post("/analyze-live")
async def analyze_live_market(
    payload: LiveAnalysisRequest,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db)
):
    """
    1-Click Live Analysis:
    1. Fetches real-time multi-timeframe candles (1m, 5m, 15m, 30m, 1h).
    2. Renders live charts automatically and attaches them as screenshots.
    3. Collects world market indicators and heavyweight impact.
    4. Triggers AI technical and macro scenario engine without requiring user image upload.
    """
    symbol = payload.symbol.strip()
    logger.info(f"Initiating 1-Click Live Analysis for symbol: {symbol}")

    mtf_data = LiveMarketService.get_multi_timeframe_data(symbol)
    base_info = mtf_data.get("base_info", {})
    timeframes = mtf_data.get("timeframes", {})

    if not timeframes:
        raise HTTPException(
            status_code=400,
            detail=f"Unable to fetch live market candles for '{symbol}'. Check symbol name."
        )

    # Global cues & heavyweights context for AI
    global_ov = LiveMarketService.get_global_market_overview()
    heavyweights = LiveMarketService.get_heavyweights_overview()
    incidents = LiveMarketService.get_market_incidents_news()

    # Formulate rich market context notes
    macro_notes = [
        f"Global Market Sentiment: {global_ov.get('global_sentiment')}.",
        f"World Indices: " + ", ".join([f"{idx['name']} ({idx['change_pct']}%)" for idx in global_ov.get('indices', [])[:4]]),
        f"Top Heavyweight Movers: " + ", ".join([f"{h['name']} ({h['change_pct']}%, {h.get('sector')})" for h in heavyweights[:4]]),
    ]
    if incidents:
        macro_notes.append(f"Recent Market Drivers: {incidents[0]['title']}")
    if payload.notes:
        macro_notes.append(f"User Note: {payload.notes}")

    combined_notes = "\n".join(macro_notes)

    # 1. Create Analysis Record
    analysis = Analysis(
        market=payload.market,
        instrument=symbol,
        instrument_type=payload.instrument_type,
        symbol=symbol,
        current_price=base_info.get("current_price"),
        previous_close=base_info.get("previous_close"),
        day_high=base_info.get("day_high"),
        day_low=base_info.get("day_low"),
        notes=combined_notes,
        status="pending"
    )
    db.add(analysis)
    db.commit()
    db.refresh(analysis)

    # 2. Render and save multi-timeframe chart images
    upload_dir = "uploads"
    os.makedirs(upload_dir, exist_ok=True)

    tf_labels_to_render = ["5 Minute", "15 Minute", "1 Hour"]
    for tf_label in tf_labels_to_render:
        tf_info = timeframes.get(tf_label)
        if tf_info and tf_info.get("candles"):
            filename = f"live_{uuid.uuid4().hex[:12]}_{symbol.replace(' ', '_')}_{tf_label.replace(' ', '')}.png"
            file_path = os.path.join(upload_dir, filename)

            rendered = LiveMarketService.render_candlestick_chart(
                candles=tf_info["candles"],
                title=f"{symbol} - {tf_label} (Live Feed)",
                output_path=file_path
            )

            if rendered:
                screenshot = AnalysisScreenshot(
                    analysis_id=analysis.id,
                    timeframe=tf_label,
                    file_path=file_path,
                    file_name=filename,
                    mime_type="image/png"
                )
                db.add(screenshot)

    db.commit()

    # 3. Trigger full AI chart analyzer in background
    async def run_bg_analysis(a_id: int, p_name: Optional[str]):
        from app.database import SessionLocal
        bg_db = SessionLocal()
        try:
            await ChartAnalyzer.run_analysis(analysis_id=a_id, db=bg_db, provider_name=p_name)
        except Exception as e:
            logger.error(f"Live Analysis background failure: {e}", exc_info=True)
            a = bg_db.query(Analysis).filter(Analysis.id == a_id).first()
            if a:
                a.status = "failed"
                a.error_message = str(e)
                bg_db.commit()
        finally:
            bg_db.close()

    background_tasks.add_task(run_bg_analysis, analysis.id, payload.ai_provider)

    return {
        "status": "success",
        "analysis_id": analysis.id,
        "message": f"Live analysis initiated for {symbol} across multiple timeframes with global market cues.",
        "base_info": base_info,
        "global_sentiment": global_ov.get("global_sentiment")
    }

@router.post("/analyze-all-live")
async def analyze_all_live_markets(
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db)
):
    """
    Triggers 1-Click Live AI Chart Analyses for ALL major Indian markets:
    - NIFTY 50
    - BANK NIFTY
    - SENSEX
    - FINNIFTY
    Generates new multi-timeframe analyses from the current moment for all markets.
    """
    symbols = [
        {"symbol": "NIFTY 50", "market": "NIFTY"},
        {"symbol": "BANK NIFTY", "market": "BANKNIFTY"},
        {"symbol": "SENSEX", "market": "SENSEX"},
        {"symbol": "FINNIFTY", "market": "FINNIFTY"},
    ]
    created = []
    for item in symbols:
        try:
            req = LiveAnalysisRequest(symbol=item["symbol"], market=item["market"])
            res = await analyze_live_market(req, background_tasks, db)
            created.append({"symbol": item["symbol"], "analysis_id": res["analysis_id"]})
        except Exception as e:
            logger.warning(f"Could not auto-analyze {item['symbol']}: {e}")

    return {
        "status": "success",
        "message": f"Successfully initiated live multi-timeframe analyses for {len(created)} markets",
        "analyses": created
    }

