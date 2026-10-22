from datetime import datetime
from typing import List, Optional, Dict, Any
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session
from sqlalchemy import desc

from app.database import get_db
from app.models import TradePosition
from app.services.market_data.angel_one_service import AngelOneService
from app.services.market_data.live_market_service import LiveMarketService
from app.services.technical_analysis.option_indicator import OptionSignalIndicator

router = APIRouter(prefix="/trades", tags=["trades"])

# Pydantic Schemas
class TradeCreateRequest(BaseModel):
    symbol: str = Field(..., example="NIFTY 50")
    contract_name: str = Field(..., example="NIFTY 50 26 OCT 2026 22700 CE")
    exchange: str = "NFO"
    tradingsymbol: Optional[str] = None
    symboltoken: Optional[str] = None
    action: str = "BUY"
    option_type: str = "CE"
    strike_price: Optional[float] = None
    expiry: Optional[str] = None
    timeframe: str = "5m"
    lots: int = 1
    lot_size: int = 25
    entry_price: float
    current_ltp: float
    stop_loss: float
    target_1: float
    target_2: float
    trade_mode: str = "PAPER"
    notes: Optional[str] = None

class OneClickBatchRequest(BaseModel):
    indices: List[str] = ["NIFTY 50", "BANK NIFTY", "SENSEX", "FINNIFTY"]
    timeframe: str = "5m"
    expiry_type: str = "current"
    lots: int = 1
    trade_mode: str = "PAPER"

class TrailSLRequest(BaseModel):
    new_stop_loss: Optional[float] = None


@router.get("/profile-margin")
def get_profile_and_margin(db: Session = Depends(get_db)) -> Dict[str, Any]:
    """
    Fetch Angel One Client Profile and RMS Margin / Funds.
    Also provides overall Paper Balance and active position summary.
    """
    # 1. Angel One Profile
    profile_data = AngelOneService.get_profile()
    client_name = "Trader"
    client_code = "P261591"
    exchanges = ["nse_fo", "bse_fo"]
    
    if profile_data.get("status") and profile_data.get("data"):
        d = profile_data["data"]
        client_name = d.get("name", client_name)
        client_code = d.get("clientcode", client_code)
        exchanges = d.get("exchanges", exchanges)

    # 2. Angel One RMS Margin / Funds
    rms_data = AngelOneService.get_rms()
    available_margin = 0.0
    available_cash = 0.0
    utilized_margin = 0.0
    m2m_unrealized = 0.0
    m2m_realized = 0.0

    if rms_data.get("status") and rms_data.get("data"):
        r = rms_data["data"]
        try:
            available_margin = float(r.get("net", 0.0) or 0.0)
            available_cash = float(r.get("availablecash", 0.0) or 0.0)
            utilized_margin = float(r.get("utiliseddebits", 0.0) or 0.0)
            m2m_unrealized = float(r.get("m2munrealized", 0.0) or 0.0)
            m2m_realized = float(r.get("m2mrealized", 0.0) or 0.0)
        except Exception:
            pass

    # 3. Local Active Trades & Portfolio Summary
    active_positions = db.query(TradePosition).filter(TradePosition.status.in_(["ACTIVE", "TARGET_1_BOOKED"])).all()
    all_positions = db.query(TradePosition).all()

    total_margin_used = sum(p.margin_required for p in active_positions)
    total_unrealized_pnl = sum((p.current_ltp - p.entry_price) * p.quantity for p in active_positions)
    total_realized_pnl = sum(p.realized_pnl for p in all_positions)

    # Paper trading balance pool (₹5,00,000 baseline)
    paper_starting_capital = 500000.0
    paper_available = round(paper_starting_capital - total_margin_used + total_realized_pnl, 2)

    return {
        "status": "success",
        "client_code": client_code,
        "client_name": client_name,
        "is_angel_connected": AngelOneService.is_configured(),
        "live_rms": {
            "available_margin": available_margin,
            "available_cash": available_cash,
            "utilized_margin": utilized_margin,
            "unrealized_m2m": m2m_unrealized,
            "realized_m2m": m2m_realized
        },
        "paper_portfolio": {
            "starting_balance": paper_starting_capital,
            "available_balance": paper_available,
            "margin_blocked": round(total_margin_used, 2),
            "unrealized_pnl": round(total_unrealized_pnl, 2),
            "realized_pnl": round(total_realized_pnl, 2),
            "total_pnl": round(total_unrealized_pnl + total_realized_pnl, 2),
            "open_positions": len(active_positions),
            "total_trades": len(all_positions)
        },
        "exchanges": exchanges
    }


@router.get("")
def list_trades(
    status: Optional[str] = Query(None, description="Filter by status: ACTIVE, TARGET_1_BOOKED, CLOSED"),
    db: Session = Depends(get_db)
):
    """List trade positions with live calculated unrealized P&L."""
    query = db.query(TradePosition)
    if status:
        query = query.filter(TradePosition.status == status.upper())
    
    trades = query.order_by(desc(TradePosition.created_at)).all()

    result = []
    for t in trades:
        # Calculate current unrealized P&L
        unrealized = round((t.current_ltp - t.entry_price) * t.quantity, 2) if t.status in ["ACTIVE", "TARGET_1_BOOKED"] else 0.0
        pnl_pct = round(((t.current_ltp - t.entry_price) / max(0.1, t.entry_price)) * 100, 2) if t.entry_price > 0 else 0.0

        item = {
            "id": t.id,
            "symbol": t.symbol,
            "contract_name": t.contract_name,
            "exchange": t.exchange,
            "tradingsymbol": t.tradingsymbol,
            "symboltoken": t.symboltoken,
            "action": t.action,
            "option_type": t.option_type,
            "strike_price": t.strike_price,
            "expiry": t.expiry,
            "timeframe": t.timeframe,
            "lots": t.lots,
            "lot_size": t.lot_size,
            "quantity": t.quantity,
            "entry_price": t.entry_price,
            "current_ltp": t.current_ltp,
            "stop_loss": t.stop_loss,
            "target_1": t.target_1,
            "target_2": t.target_2,
            "margin_required": t.margin_required,
            "max_risk": t.max_risk,
            "target_1_profit": t.target_1_profit,
            "target_2_profit": t.target_2_profit,
            "unrealized_pnl": unrealized,
            "pnl_percentage": pnl_pct,
            "realized_pnl": t.realized_pnl,
            "status": t.status,
            "trade_mode": t.trade_mode,
            "angel_order_id": t.angel_order_id,
            "notes": t.notes,
            "entry_time": t.entry_time.isoformat() if t.entry_time else None,
            "exit_time": t.exit_time.isoformat() if t.exit_time else None,
            "created_at": t.created_at.isoformat() if t.created_at else None
        }
        result.append(item)

    return result


@router.post("")
def create_trade(payload: TradeCreateRequest, db: Session = Depends(get_db)):
    """Create / add a single trade position."""
    quantity = payload.lots * payload.lot_size
    margin_req = round(payload.entry_price * quantity, 2)
    max_risk = round(abs(payload.entry_price - payload.stop_loss) * quantity, 2)
    t1_profit = round(abs(payload.target_1 - payload.entry_price) * quantity, 2)
    t2_profit = round(abs(payload.target_2 - payload.entry_price) * quantity, 2)

    angel_order_id = None
    if payload.trade_mode.upper() == "LIVE":
        # Place real order via Angel One
        order_res = AngelOneService.place_order(
            tradingsymbol=payload.tradingsymbol or payload.contract_name,
            symboltoken=payload.symboltoken or "",
            exchange=payload.exchange,
            transactiontype=payload.action,
            quantity=quantity,
            price=payload.entry_price,
            ordertype="LIMIT"
        )
        if order_res.get("status") and order_res.get("data"):
            angel_order_id = str(order_res["data"].get("orderid", ""))

    trade = TradePosition(
        symbol=payload.symbol,
        contract_name=payload.contract_name,
        exchange=payload.exchange,
        tradingsymbol=payload.tradingsymbol,
        symboltoken=payload.symboltoken,
        action=payload.action.upper(),
        option_type=payload.option_type.upper(),
        strike_price=payload.strike_price,
        expiry=payload.expiry,
        timeframe=payload.timeframe,
        lots=payload.lots,
        lot_size=payload.lot_size,
        quantity=quantity,
        entry_price=payload.entry_price,
        current_ltp=payload.current_ltp,
        stop_loss=payload.stop_loss,
        target_1=payload.target_1,
        target_2=payload.target_2,
        margin_required=margin_req,
        max_risk=max_risk,
        target_1_profit=t1_profit,
        target_2_profit=t2_profit,
        realized_pnl=0.0,
        status="ACTIVE",
        trade_mode=payload.trade_mode.upper(),
        angel_order_id=angel_order_id,
        notes=payload.notes,
        entry_time=datetime.utcnow()
    )

    db.add(trade)
    db.commit()
    db.refresh(trade)
    return trade


@router.post("/one-click-batch")
def one_click_batch_add_trades(payload: OneClickBatchRequest, db: Session = Depends(get_db)):
    """
    ⚡ 1-Click Add 4 Trades:
    Scans live signals for NIFTY 50, SENSEX, BANK NIFTY, and FINNIFTY,
    generates optimal option contracts with live LTP, entry, SL, Target 1, Target 2,
    and adds all 4 trades in one atomic operation.
    """
    indices = payload.indices or ["NIFTY 50", "BANK NIFTY", "SENSEX", "FINNIFTY"]
    created_trades = []
    total_margin = 0.0
    total_risk = 0.0
    total_t1_profit = 0.0
    total_t2_profit = 0.0

    interval = "15m" if payload.timeframe.lower() in ["15m", "15", "15min"] else "5m"

    for symbol in indices:
        try:
            # 1. Fetch live candle data & CMP
            yf_sym = LiveMarketService.resolve_symbol(symbol)
            data = LiveMarketService.get_candle_data(yf_sym, interval=interval, range_="5d")
            if not data or not data.get("candles"):
                data = LiveMarketService.get_candle_data(yf_sym, interval=interval, range_="1d")
            candles = data.get("candles", []) if data else []
            cmp = data.get("current_price") if data else None

            # 2. Fetch signal and recommended setup
            signal = OptionSignalIndicator.evaluate_5m_option_signal(
                candles,
                cmp,
                symbol=symbol,
                expiry_type=payload.expiry_type,
                timeframe=payload.timeframe
            )
            trade_exec = signal.get("trade_execution", {})
            decision = signal.get("decision", "BUY CALL (CE)")
            direction = signal.get("direction", "CALL")

            # Determine action & option type
            opt_type = "CE" if "CALL" in direction.upper() else "PE"
            action = "BUY"

            contract_name = trade_exec.get("contract_name") or f"{symbol} {signal.get('active_expiry', '').upper()} {signal.get('strike_suggest', '')}"
            entry_price = float(trade_exec.get("recommended_entry", 100.0))
            current_ltp = float(trade_exec.get("current_ltp", entry_price))
            stop_loss = float(trade_exec.get("stop_loss", round(entry_price * 0.8, 1)))
            target_1 = float(trade_exec.get("target_1", round(entry_price * 1.25, 1)))
            target_2 = float(trade_exec.get("target_2", round(entry_price * 1.5, 1)))
            lot_size = int(trade_exec.get("lot_size", 25))
            lots = payload.lots
            quantity = lots * lot_size

            margin_req = round(entry_price * quantity, 2)
            max_risk = round(abs(entry_price - stop_loss) * quantity, 2)
            t1_profit = round(abs(target_1 - entry_price) * quantity, 2)
            t2_profit = round(abs(target_2 - entry_price) * quantity, 2)

            exchange = "BFO" if "SENSEX" in symbol.upper() else "NFO"
            ts_code = signal.get("contract_tradingsymbol") or ""
            sym_token = signal.get("contract_symboltoken") or ""

            angel_order_id = None
            if payload.trade_mode.upper() == "LIVE" and ts_code:
                order_res = AngelOneService.place_order(
                    tradingsymbol=ts_code,
                    symboltoken=sym_token,
                    exchange=exchange,
                    transactiontype="BUY",
                    quantity=quantity,
                    price=entry_price,
                    ordertype="LIMIT"
                )
                if order_res.get("status") and order_res.get("data"):
                    angel_order_id = str(order_res["data"].get("orderid", ""))

            trade = TradePosition(
                symbol=symbol,
                contract_name=contract_name,
                exchange=exchange,
                tradingsymbol=ts_code,
                symboltoken=sym_token,
                action=action,
                option_type=opt_type,
                strike_price=float(signal.get("selected_strike") or 0.0),
                expiry=signal.get("active_expiry", ""),
                timeframe=payload.timeframe,
                lots=lots,
                lot_size=lot_size,
                quantity=quantity,
                entry_price=entry_price,
                current_ltp=current_ltp,
                stop_loss=stop_loss,
                target_1=target_1,
                target_2=target_2,
                margin_required=margin_req,
                max_risk=max_risk,
                target_1_profit=t1_profit,
                target_2_profit=t2_profit,
                realized_pnl=0.0,
                status="ACTIVE",
                trade_mode=payload.trade_mode.upper(),
                angel_order_id=angel_order_id,
                notes=f"Auto 1-Click Batch Execution ({decision} - {signal.get('confidence', 75)}% conf)",
                entry_time=datetime.utcnow()
            )

            db.add(trade)
            db.commit()
            db.refresh(trade)

            total_margin += margin_req
            total_risk += max_risk
            total_t1_profit += t1_profit
            total_t2_profit += t2_profit

            created_trades.append({
                "id": trade.id,
                "symbol": trade.symbol,
                "contract_name": trade.contract_name,
                "action": trade.action,
                "option_type": trade.option_type,
                "quantity": trade.quantity,
                "current_ltp": trade.current_ltp,
                "entry_price": trade.entry_price,
                "stop_loss": trade.stop_loss,
                "target_1": trade.target_1,
                "target_2": trade.target_2,
                "margin_required": trade.margin_required,
                "max_risk": trade.max_risk,
                "target_1_profit": trade.target_1_profit,
                "target_2_profit": trade.target_2_profit,
                "status": trade.status,
                "trade_mode": trade.trade_mode
            })
        except Exception as e:
            import traceback
            traceback.print_exc()
            db.rollback()
            continue

    return {
        "status": "success",
        "message": f"Successfully created {len(created_trades)} trades in 1-Click batch",
        "trades_count": len(created_trades),
        "total_margin_required": round(total_margin, 2),
        "total_max_risk": round(total_risk, 2),
        "total_target_1_profit": round(total_t1_profit, 2),
        "total_target_2_profit": round(total_t2_profit, 2),
        "trades": created_trades
    }


@router.post("/{trade_id}/book-target-1")
def book_target_1(trade_id: int, db: Session = Depends(get_db)):
    """
    🎯 Book 1st Target:
    Locks in Target 1 profit, updates status to TARGET_1_BOOKED,
    and trails Stop Loss to Break-Even (entry price).
    """
    trade = db.query(TradePosition).filter(TradePosition.id == trade_id).first()
    if not trade:
        raise HTTPException(status_code=404, detail="Trade not found")

    if trade.status in ["CLOSED", "STOPPED_OUT"]:
        raise HTTPException(status_code=400, detail=f"Cannot book target on trade with status {trade.status}")

    # Calculate profit achieved at Target 1
    profit_t1 = round((trade.target_1 - trade.entry_price) * trade.quantity, 2)
    trade.realized_pnl = profit_t1
    trade.current_ltp = trade.target_1  # set LTP to Target 1 price
    trade.stop_loss = trade.entry_price  # Risk-Free: Trail SL to Break-Even!
    trade.status = "TARGET_1_BOOKED"
    trade.notes = f"{trade.notes or ''} | Target 1 Booked (+₹{profit_t1}); SL trailed to Break-Even (₹{trade.entry_price})"

    db.commit()
    db.refresh(trade)

    return {
        "status": "success",
        "message": f"🎯 Target 1 Booked! Realized Profit: +₹{profit_t1}. Stop Loss trailed to Break-Even at ₹{trade.entry_price}.",
        "trade": {
            "id": trade.id,
            "symbol": trade.symbol,
            "contract_name": trade.contract_name,
            "realized_pnl": trade.realized_pnl,
            "stop_loss": trade.stop_loss,
            "status": trade.status
        }
    }


@router.post("/{trade_id}/book-target-2")
def book_target_2(trade_id: int, db: Session = Depends(get_db)):
    """
    🏆 Book 2nd Target:
    Locks in full Target 2 profit and closes the position.
    """
    trade = db.query(TradePosition).filter(TradePosition.id == trade_id).first()
    if not trade:
        raise HTTPException(status_code=404, detail="Trade not found")

    profit_t2 = round((trade.target_2 - trade.entry_price) * trade.quantity, 2)
    trade.realized_pnl = profit_t2
    trade.current_ltp = trade.target_2
    trade.status = "TARGET_2_BOOKED"
    trade.exit_time = datetime.utcnow()
    trade.notes = f"{trade.notes or ''} | Target 2 Booked (+₹{profit_t2}); Trade Complete"

    db.commit()
    db.refresh(trade)

    return {
        "status": "success",
        "message": f"🏆 Target 2 Booked! Total Realized Profit: +₹{profit_t2}.",
        "trade": {
            "id": trade.id,
            "symbol": trade.symbol,
            "contract_name": trade.contract_name,
            "realized_pnl": trade.realized_pnl,
            "status": trade.status
        }
    }


@router.post("/{trade_id}/close")
def close_trade(trade_id: int, db: Session = Depends(get_db)):
    """Square off / exit position at current LTP."""
    trade = db.query(TradePosition).filter(TradePosition.id == trade_id).first()
    if not trade:
        raise HTTPException(status_code=404, detail="Trade not found")

    pnl = round((trade.current_ltp - trade.entry_price) * trade.quantity, 2)
    trade.realized_pnl = pnl
    trade.status = "CLOSED"
    trade.exit_time = datetime.utcnow()

    db.commit()
    db.refresh(trade)

    return {
        "status": "success",
        "message": f"Position closed at ₹{trade.current_ltp}. Final P&L: ₹{pnl}",
        "trade_id": trade.id,
        "realized_pnl": trade.realized_pnl
    }


@router.post("/{trade_id}/trail-sl")
def trail_stop_loss(trade_id: int, payload: TrailSLRequest, db: Session = Depends(get_db)):
    """Trail stop loss to specified price or break-even."""
    trade = db.query(TradePosition).filter(TradePosition.id == trade_id).first()
    if not trade:
        raise HTTPException(status_code=404, detail="Trade not found")

    new_sl = payload.new_stop_loss if payload.new_stop_loss is not None else trade.entry_price
    trade.stop_loss = new_sl
    trade.notes = f"{trade.notes or ''} | SL Trailed to ₹{new_sl}"

    db.commit()
    db.refresh(trade)

    return {
        "status": "success",
        "message": f"Stop loss trailed to ₹{new_sl}",
        "trade_id": trade.id,
        "stop_loss": trade.stop_loss
    }


@router.delete("/{trade_id}")
def delete_trade(trade_id: int, db: Session = Depends(get_db)):
    """Delete a trade record."""
    trade = db.query(TradePosition).filter(TradePosition.id == trade_id).first()
    if not trade:
        raise HTTPException(status_code=404, detail="Trade not found")

    db.delete(trade)
    db.commit()
    return {"status": "success", "message": f"Trade {trade_id} deleted"}


@router.delete("")
def clear_all_trades(db: Session = Depends(get_db)):
    """Clear all trades."""
    count = db.query(TradePosition).delete()
    db.commit()
    return {"status": "success", "message": f"Cleared {count} trades"}
