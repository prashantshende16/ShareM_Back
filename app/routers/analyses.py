import json
import logging
from typing import List, Optional
from datetime import datetime
from fastapi import APIRouter, Depends, HTTPException, Query, BackgroundTasks
from sqlalchemy.orm import Session
from sqlalchemy import desc

from app.database import get_db
from app.models import Analysis, AnalysisScreenshot, AnalysisResult, ScenarioPrediction, WatchlistItem
from app.schemas import (
    AnalysisCreate,
    AnalysisResponse,
    AnalysisResultResponse,
    DashboardStats,
    CompareResponse
)
from app.services.chart_analysis.chart_analyzer import ChartAnalyzer
from app.utils.file_upload import remove_screenshot_file

router = APIRouter(prefix="/analyses", tags=["Analyses"])
logger = logging.getLogger(__name__)

def parse_result_model(r: AnalysisResult) -> dict:
    if not r:
        return None
    return {
        "id": r.id,
        "analysis_id": r.analysis_id,
        "trend": r.trend,
        "primary_scenario": r.primary_scenario,
        "confidence_score": r.confidence_score,
        "market_structure": json.loads(r.market_structure) if r.market_structure else {},
        "support_levels": json.loads(r.support_levels) if r.support_levels else [],
        "resistance_levels": json.loads(r.resistance_levels) if r.resistance_levels else [],
        "candlestick_analysis": json.loads(r.candlestick_analysis) if r.candlestick_analysis else {},
        "volume_analysis": json.loads(r.volume_analysis) if r.volume_analysis else {},
        "oi_analysis": json.loads(r.oi_analysis) if r.oi_analysis else {},
        "technical_indicators": json.loads(r.technical_indicators) if r.technical_indicators else {},
        "bullish_scenario": json.loads(r.bullish_scenario) if r.bullish_scenario else {},
        "bearish_scenario": json.loads(r.bearish_scenario) if r.bearish_scenario else {},
        "sideways_scenario": json.loads(r.sideways_scenario) if r.sideways_scenario else {},
        "risk_analysis": json.loads(r.risk_analysis) if r.risk_analysis else {},
        "trade_setup": json.loads(r.trade_setup) if r.trade_setup else {},
        "time_movements": json.loads(r.time_movements) if r.time_movements else [],
        "multi_timeframe_synthesis": json.loads(r.multi_timeframe_synthesis) if r.multi_timeframe_synthesis else {},
        "detected_overlays": json.loads(r.detected_overlays) if r.detected_overlays else [],
        "entry_zone": r.entry_zone,
        "stop_loss_zone": r.stop_loss_zone,
        "target_zone": r.target_zone,
        "confirmation_conditions": json.loads(r.confirmation_conditions) if r.confirmation_conditions else [],
        "invalidating_conditions": json.loads(r.invalidating_conditions) if r.invalidating_conditions else [],
        "time_horizon": r.time_horizon,
        "ai_summary": r.ai_summary,
        "created_at": r.created_at
    }

def format_analysis_response(a: Analysis) -> dict:
    screenshots = [
        {
            "id": s.id,
            "analysis_id": s.analysis_id,
            "timeframe": s.timeframe,
            "file_path": s.file_path,
            "file_name": s.file_name,
            "mime_type": s.mime_type,
            "url": f"/uploads/{s.file_name}",
            "created_at": s.created_at
        }
        for s in a.screenshots
    ]
    scenarios = [
        {
            "id": sc.id,
            "scenario_type": sc.scenario_type,
            "probability": sc.probability,
            "expected_direction": sc.expected_direction,
            "expected_range": sc.expected_range,
            "timeframe": sc.timeframe,
            "trigger_condition": sc.trigger_condition,
            "invalidation_condition": sc.invalidation_condition
        }
        for sc in a.scenarios
    ]
    return {
        "id": a.id,
        "user_id": a.user_id,
        "market": a.market,
        "instrument": a.instrument,
        "instrument_type": a.instrument_type,
        "symbol": a.symbol,
        "expiry": a.expiry,
        "strike_price": a.strike_price,
        "option_type": a.option_type,
        "current_price": a.current_price,
        "previous_close": a.previous_close,
        "day_high": a.day_high,
        "day_low": a.day_low,
        "volume": a.volume,
        "open_interest": a.open_interest,
        "pcr": a.pcr,
        "india_vix": a.india_vix,
        "notes": a.notes,
        "status": a.status,
        "error_message": a.error_message,
        "created_at": a.created_at,
        "updated_at": a.updated_at,
        "screenshots": screenshots,
        "result": parse_result_model(a.result) if a.result else None,
        "scenarios": scenarios
    }

@router.get("/stats", response_model=DashboardStats)
def get_dashboard_stats(db: Session = Depends(get_db)):
    analyses = db.query(Analysis).all()
    total = len(analyses)
    bullish = 0
    bearish = 0
    sideways = 0
    high_conf = 0

    for a in analyses:
        if a.result:
            p = (a.result.primary_scenario or "").lower()
            if "bull" in p:
                bullish += 1
            elif "bear" in p:
                bearish += 1
            else:
                sideways += 1

            if a.result.confidence_score >= 70:
                high_conf += 1

    return DashboardStats(
        total_analyses=total,
        bullish_scenarios=bullish,
        bearish_scenarios=bearish,
        sideways_scenarios=sideways,
        high_confidence_analyses=high_conf
    )

@router.post("", response_model=AnalysisResponse)
def create_analysis(data: AnalysisCreate, db: Session = Depends(get_db)):
    analysis = Analysis(
        market=data.market,
        instrument=data.instrument or data.symbol,
        instrument_type=data.instrument_type,
        symbol=data.symbol,
        expiry=data.expiry,
        strike_price=data.strike_price,
        option_type=data.option_type,
        current_price=data.current_price,
        previous_close=data.previous_close,
        day_high=data.day_high,
        day_low=data.day_low,
        volume=data.volume,
        open_interest=data.open_interest,
        pcr=data.pcr,
        india_vix=data.india_vix,
        notes=data.notes,
        status="pending"
    )
    db.add(analysis)
    db.commit()
    db.refresh(analysis)
    return format_analysis_response(analysis)

@router.get("", response_model=List[AnalysisResponse])
def list_analyses(
    symbol: Optional[str] = Query(None),
    market: Optional[str] = Query(None),
    bias: Optional[str] = Query(None),
    min_confidence: Optional[int] = Query(None),
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=100),
    db: Session = Depends(get_db)
):
    query = db.query(Analysis).order_by(desc(Analysis.created_at))

    if symbol:
        query = query.filter(Analysis.symbol.ilike(f"%{symbol}%"))
    if market:
        query = query.filter(Analysis.market == market)

    analyses = query.offset(skip).limit(limit).all()

    # Filter by result fields if requested
    results = []
    for a in analyses:
        if bias and a.result:
            if bias.lower() not in (a.result.primary_scenario or "").lower():
                continue
        if min_confidence and a.result:
            if a.result.confidence_score < min_confidence:
                continue
        results.append(format_analysis_response(a))

    return results

@router.get("/{id}", response_model=AnalysisResponse)
def get_analysis(id: int, db: Session = Depends(get_db)):
    analysis = db.query(Analysis).filter(Analysis.id == id).first()
    if not analysis:
        raise HTTPException(status_code=404, detail="Analysis not found")
    return format_analysis_response(analysis)

@router.get("/{id}/result", response_model=AnalysisResultResponse)
def get_analysis_result(id: int, db: Session = Depends(get_db)):
    analysis = db.query(Analysis).filter(Analysis.id == id).first()
    if not analysis:
        raise HTTPException(status_code=404, detail="Analysis not found")
    if not analysis.result:
        raise HTTPException(status_code=404, detail="Analysis result has not been generated yet")
    return parse_result_model(analysis.result)

@router.post("/{id}/run", response_model=AnalysisResponse)
async def run_analysis(id: int, background_tasks: BackgroundTasks, db: Session = Depends(get_db)):
    analysis = db.query(Analysis).filter(Analysis.id == id).first()
    if not analysis:
        raise HTTPException(status_code=404, detail="Analysis not found")

    # Run synchronously or in background
    # We do synchronous await so the client gets immediate completion,
    # and errors are surfaced clearly, while keeping status updated
    try:
        await ChartAnalyzer.run_analysis(analysis_id=id, db=db)
    except Exception as e:
        logger.error(f"Analysis failed: {e}")
        db.refresh(analysis)
        raise HTTPException(status_code=500, detail=str(e))

    db.refresh(analysis)
    
    # Update watchlist last_analysis_id if symbol matches
    w_item = db.query(WatchlistItem).filter(WatchlistItem.symbol == analysis.symbol).first()
    if w_item:
        w_item.last_analysis_id = analysis.id
        db.commit()

    return format_analysis_response(analysis)

@router.delete("/{id}")
def delete_analysis(id: int, db: Session = Depends(get_db)):
    analysis = db.query(Analysis).filter(Analysis.id == id).first()
    if not analysis:
        raise HTTPException(status_code=404, detail="Analysis not found")

    # Clean up screenshot files
    for s in analysis.screenshots:
        remove_screenshot_file(s.file_path)

    db.delete(analysis)
    db.commit()
    return {"message": f"Analysis {id} deleted successfully"}

@router.get("/compare/{id1}/{id2}", response_model=CompareResponse)
def compare_analyses(id1: int, id2: int, db: Session = Depends(get_db)):
    a1 = db.query(Analysis).filter(Analysis.id == id1).first()
    a2 = db.query(Analysis).filter(Analysis.id == id2).first()
    if not a1 or not a2:
        raise HTTPException(status_code=404, detail="One or both analyses not found")

    bias1 = a1.result.primary_scenario if a1.result else "N/A"
    bias2 = a2.result.primary_scenario if a2.result else "N/A"
    conf1 = a1.result.confidence_score if a1.result else 0
    conf2 = a2.result.confidence_score if a2.result else 0

    s1_levels = json.loads(a1.result.support_levels) if a1.result and a1.result.support_levels else []
    s2_levels = json.loads(a2.result.support_levels) if a2.result and a2.result.support_levels else []
    r1_levels = json.loads(a1.result.resistance_levels) if a1.result and a1.result.resistance_levels else []
    r2_levels = json.loads(a2.result.resistance_levels) if a2.result and a2.result.resistance_levels else []

    diff = {
        "bias_shift": f"{bias1.upper()} → {bias2.upper()}",
        "confidence_shift": f"{conf1}% → {conf2}% ({conf2 - conf1:+d}%)",
        "primary_support_1": s1_levels[0].get("price") if s1_levels else "N/A",
        "primary_support_2": s2_levels[0].get("price") if s2_levels else "N/A",
        "primary_resistance_1": r1_levels[0].get("price") if r1_levels else "N/A",
        "primary_resistance_2": r2_levels[0].get("price") if r2_levels else "N/A",
        "trend_comparison": f"{a1.result.trend if a1.result else 'N/A'} vs {a2.result.trend if a2.result else 'N/A'}"
    }

    return {
        "analysis_1": format_analysis_response(a1),
        "analysis_2": format_analysis_response(a2),
        "diff": diff
    }
