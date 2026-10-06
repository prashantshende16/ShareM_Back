from typing import List
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from datetime import datetime

from app.database import get_db
from app.models import WatchlistItem, Analysis
from app.schemas import WatchlistItemCreate, WatchlistItemResponse

router = APIRouter(prefix="/watchlist", tags=["Watchlist"])

DEFAULT_WATCHLIST = [
    {"symbol": "NIFTY 50", "market": "NSE"},
    {"symbol": "BANKNIFTY", "market": "NSE"},
    {"symbol": "FINNIFTY", "market": "NSE"},
    {"symbol": "SENSEX", "market": "BSE"},
    {"symbol": "RELIANCE", "market": "NSE"},
    {"symbol": "TCS", "market": "NSE"},
    {"symbol": "INFY", "market": "NSE"}
]

def seed_defaults_if_empty(db: Session):
    count = db.query(WatchlistItem).count()
    if count == 0:
        for item in DEFAULT_WATCHLIST:
            db.add(WatchlistItem(symbol=item["symbol"], market=item["market"]))
        db.commit()

@router.get("", response_model=List[WatchlistItemResponse])
def get_watchlist(db: Session = Depends(get_db)):
    seed_defaults_if_empty(db)
    items = db.query(WatchlistItem).all()

    result = []
    for item in items:
        # Check if there is an analysis for this symbol
        analysis = (
            db.query(Analysis)
            .filter(Analysis.symbol.ilike(f"%{item.symbol}%"))
            .order_by(Analysis.created_at.desc())
            .first()
        )
        bias = "N/A"
        conf = None
        timeframe = None
        updated = item.updated_at

        if analysis and analysis.result:
            bias = analysis.result.primary_scenario.upper()
            conf = analysis.result.confidence_score
            updated = analysis.result.created_at
            if analysis.screenshots:
                timeframe = analysis.screenshots[0].timeframe

        result.append(WatchlistItemResponse(
            id=item.id,
            symbol=item.symbol,
            market=item.market,
            last_analysis_id=analysis.id if analysis else None,
            last_bias=bias,
            last_confidence=conf,
            last_timeframe=timeframe,
            last_updated=updated
        ))
    return result

@router.post("", response_model=WatchlistItemResponse)
def add_to_watchlist(data: WatchlistItemCreate, db: Session = Depends(get_db)):
    existing = db.query(WatchlistItem).filter(WatchlistItem.symbol.ilike(data.symbol)).first()
    if existing:
        raise HTTPException(status_code=400, detail="Symbol already in watchlist")

    item = WatchlistItem(symbol=data.symbol.upper(), market=data.market)
    db.add(item)
    db.commit()
    db.refresh(item)
    return WatchlistItemResponse(
        id=item.id,
        symbol=item.symbol,
        market=item.market,
        last_analysis_id=None,
        last_bias="N/A",
        last_confidence=None,
        last_timeframe=None,
        last_updated=item.updated_at
    )

@router.delete("/{id}")
def delete_from_watchlist(id: int, db: Session = Depends(get_db)):
    item = db.query(WatchlistItem).filter(WatchlistItem.id == id).first()
    if not item:
        raise HTTPException(status_code=404, detail="Watchlist item not found")
    db.delete(item)
    db.commit()
    return {"message": "Symbol removed from watchlist"}
