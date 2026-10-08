import os
import uuid
import logging
from typing import Optional
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

