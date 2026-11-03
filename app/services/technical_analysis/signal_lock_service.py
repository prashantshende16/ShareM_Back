"""
Signal Lock / Stabilizer Service
================================

Fixes the "CALL / PUT changes every 30 seconds" problem.

Rules
-----
1. CLOSED CANDLES ONLY  - the still-forming candle is ignored for the CALL/PUT
   decision, so the direction can only change at a candle close.
2. 2-CANDLE CONFIRMATION - a new CALL/PUT is created only when the last
   2 closed candles BOTH agree with a strong score gap (>= ENTER_GAP).
3. HYSTERESIS           - once locked, the signal is kept while the score gap in
   its favour stays >= HOLD_GAP (checked once per closed candle).
4. LOCK UNTIL RESOLVED  - Entry / SL / T1 / T2 are frozen. The signal stays until
   SL hit, T2 hit, setup weakens, or MAX_LOCK_MINUTES pass.
   T1 hit -> SL is trailed to entry (cost) and the trade rides towards T2.
5. JOURNAL              - every resolved signal is saved with its real outcome so
   the true win-rate can be measured (GET /market/signal-performance).
"""
import os
import json
import time
import threading
import logging
from datetime import datetime
from typing import Any, Dict, List, Optional

import pytz

logger = logging.getLogger(__name__)

IST = pytz.timezone("Asia/Kolkata")
JOURNAL_FILE = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "uploads", "signal_outcomes.json"
)

SYMBOL_ALIASES = {
    "^NSEI": "NIFTY 50", "NIFTY": "NIFTY 50", "NIFTY50": "NIFTY 50",
    "^NSEBANK": "BANK NIFTY", "BANKNIFTY": "BANK NIFTY", "NIFTY BANK": "BANK NIFTY",
    "^BSESN": "SENSEX",
    "NIFTY_FIN_SERVICE.NS": "FINNIFTY", "NIFTY FIN SERVICE": "FINNIFTY",
    "NIFTY_MID_SELECT.NS": "MIDCPNIFTY", "MIDCAP NIFTY": "MIDCPNIFTY",
}

OPEN_STATES = {"PENDING_ENTRY", "ACTIVE", "T1_HIT"}

STATUS_TEXT = {
    "PENDING_ENTRY": "⏳ Waiting for entry trigger",
    "ACTIVE": "🟢 Trade active - hold with SL",
    "T1_HIT": "🎯 Target 1 hit - SL moved to cost, riding to T2",
    "T2_HIT": "🏆 Target 2 hit - full profit booked",
    "T1_THEN_COST": "✅ T1 booked, rest exited at cost",
    "T1_EXIT": "✅ T1 booked, rest exited (setup weakened / time)",
    "SL_HIT": "🛑 Stop loss hit - exit",
    "EXIT_WEAK": "⚠️ Setup weakened - exited at market",
    "TIME_EXIT": "⌛ 30-min limit reached - exited at market",
    "CANCELLED": "✖ Setup failed before entry - no trade",
    "EXPIRED_NO_ENTRY": "⌛ Entry never triggered - no trade",
}


class SignalLockService:
    ENTER_GAP = 25          # raw point gap needed on BOTH last 2 closed candles to create a signal
    ENTER_PCT = 60          # winning side must hold >= 60% of the points
    HOLD_GAP = 10           # keep the lock while favour gap >= 10 (hysteresis)
    CONFIRM_CANDLES = 2
    MAX_LOCK_MINUTES = 30

    FAST_GAP = 40           # live score gap needed for the fast path
    FAST_PCT = 70
    FAST_HOLD_SEC = 10      # live move must persist across polls for this long

    _locks: Dict[str, Dict[str, Any]] = {}
    _fast: Dict[str, Dict[str, Any]] = {}
    _lock = threading.Lock()
    _journal_lock = threading.Lock()

    # ------------------------------------------------------------------ helpers
    @staticmethod
    def _norm_symbol(symbol: Optional[str]) -> str:
        s = (symbol or "NIFTY 50").strip().upper()
        return SYMBOL_ALIASES.get(s, s)

    @staticmethod
    def _tf(timeframe: str):
        tf = str(timeframe or "5m").strip().lower()
        if tf in ["1h", "60m", "60", "1 hour"]:
            return "1h", 3600
        if tf in ["30m", "30", "30min", "30 minute"]:
            return "30m", 1800
        if tf in ["15m", "15", "15min", "15 minute"]:
            return "15m", 900
        return "5m", 300

    @staticmethod
    def _closed_candles(candles: List[Dict[str, Any]], tf_sec: int, now: float) -> List[Dict[str, Any]]:
        """Drop the still-forming last candle (its start + interval is in the future)."""
        if not candles:
            return []
        last_t = candles[-1].get("time")
        if last_t:
            try:
                if float(last_t) + tf_sec > now + 1:
                    return candles[:-1]
                return candles
            except (TypeError, ValueError):
                pass
        return candles[:-1]

    @classmethod
    def _side(cls, s: Dict[str, Any], gap: int, pct: int) -> Optional[str]:
        if not s or "call_points" not in s:
            return None
        cp, pp = s["call_points"], s["put_points"]
        if cp - pp >= gap and s["call_pct"] >= pct:
            return "CALL"
        if pp - cp >= gap and s["put_pct"] >= pct:
            return "PUT"
        return None

    @classmethod
    def _fast_trigger(cls, key: str, s_live: Dict[str, Any], s_closed: Dict[str, Any], now: float) -> Optional[str]:
        """Return CALL/PUT when a strong live move has persisted and the last closed candle doesn't oppose it."""
        side = cls._side(s_live, cls.FAST_GAP, cls.FAST_PCT)
        # A closed candle that opposes the move blocks the fast path, unless the live
        # move is extreme (2x gap) - i.e. a genuine sharp reversal we must not miss.
        if not side or (cls._favour(s_closed, side) < 0 and cls._favour(s_live, side) < cls.FAST_GAP * 2):
            cls._fast.pop(key, None)
            return None
        rec = cls._fast.get(key)
        if not rec or rec["side"] != side:
            cls._fast[key] = {"side": side, "first": now}
            return None
        return side if (now - rec["first"]) >= cls.FAST_HOLD_SEC else None

    @staticmethod
    def _favour(s: Dict[str, Any], direction: str) -> float:
        if not s or "call_points" not in s:
            return 0.0
        d = s["call_points"] - s["put_points"]
        return d if direction == "CALL" else -d

    @staticmethod
    def _fmt(ts: Optional[float]) -> Optional[str]:
        if not ts:
            return None
        return datetime.fromtimestamp(ts, tz=IST).strftime("%I:%M:%S %p")

    # ------------------------------------------------------------------ state machine
    @classmethod
    def _advance(cls, st: Dict[str, Any], ltp: float, now: float, weak: bool):
        expired = (now - st["locked_at"]) >= cls.MAX_LOCK_MINUTES * 60
        status = st["status"]

        def close(final: str, exit_price: float):
            st["status"] = final
            st["exit_price"] = round(exit_price, 2)
            st["resolved_at"] = now

        if ltp <= 0:
            if expired:
                close("EXPIRED_NO_ENTRY" if status == "PENDING_ENTRY" else "TIME_EXIT", st.get("last_ltp", st["entry"]))
            return
        st["last_ltp"] = ltp

        if status == "PENDING_ENTRY":
            if ltp >= st["entry"]:
                st["status"] = "ACTIVE"
                st["entered_at"] = now
                status = "ACTIVE"
            elif ltp <= st["sl"] or weak:
                close("CANCELLED", ltp)
                return
            elif expired:
                close("EXPIRED_NO_ENTRY", ltp)
                return

        if status == "ACTIVE":
            if ltp <= st["sl"]:
                close("SL_HIT", st["sl"])
            elif ltp >= st["t2"]:
                close("T2_HIT", st["t2"])
            elif ltp >= st["t1"]:
                st["status"] = "T1_HIT"
                st["t1_hit_at"] = now
                st["sl"] = st["entry"]  # trail SL to cost
            elif weak:
                close("EXIT_WEAK", ltp)
            elif expired:
                close("TIME_EXIT", ltp)
            return

        if status == "T1_HIT":
            if ltp >= st["t2"]:
                close("T2_HIT", st["t2"])
            elif ltp <= st["sl"]:
                close("T1_THEN_COST", st["entry"])
            elif weak or expired:
                close("T1_EXIT", ltp)

    # ------------------------------------------------------------------ journal
    @classmethod
    def _journal(cls, st: Dict[str, Any]):
        status = st["status"]
        entered = st.get("entered_at") is not None
        entry = st["entry"]
        exit_price = st.get("exit_price", entry)
        t1_reached = st.get("t1_hit_at") is not None or status == "T2_HIT"

        if not entered:
            result, pnl_pts = "NO_TRADE", 0.0
        elif t1_reached:
            # half booked at T1, rest at exit
            pnl_pts = round(((st["t1"] - entry) + (exit_price - entry)) / 2.0, 2)
            result = "WIN"
        else:
            pnl_pts = round(exit_price - entry, 2)
            result = "WIN" if pnl_pts > 0 else ("LOSS" if pnl_pts < 0 else "FLAT")

        record = {
            "id": st["id"],
            "symbol": st["symbol"],
            "timeframe": st["timeframe"],
            "direction": st["direction"],
            "contract": st.get("contract"),
            "strike": st.get("strike"),
            "option_type": st.get("option_type"),
            "confidence": st.get("confidence"),
            "entry": entry,
            "stop_loss": st["sl_initial"],
            "target_1": st["t1"],
            "target_2": st["t2"],
            "exit_price": exit_price,
            "status": status,
            "result": result,
            "pnl_points": pnl_pts,
            "pnl_amount": round(pnl_pts * (st.get("lot_size") or 1), 2),
            "locked_at": datetime.fromtimestamp(st["locked_at"], tz=IST).isoformat(),
            "resolved_at": datetime.fromtimestamp(st.get("resolved_at", time.time()), tz=IST).isoformat(),
            "date": datetime.fromtimestamp(st["locked_at"], tz=IST).strftime("%Y-%m-%d"),
        }
        with cls._journal_lock:
            try:
                os.makedirs(os.path.dirname(JOURNAL_FILE), exist_ok=True)
                data = []
                if os.path.exists(JOURNAL_FILE):
                    with open(JOURNAL_FILE, "r") as f:
                        data = json.load(f)
                if any(r.get("id") == record["id"] for r in data):
                    return
                data.insert(0, record)
                with open(JOURNAL_FILE, "w") as f:
                    json.dump(data[:1000], f, indent=2)
            except Exception as e:
                logger.warning(f"Could not write signal journal: {e}")

    @classmethod
    def get_performance(cls, date: Optional[str] = None, min_confidence: int = 0) -> Dict[str, Any]:
        data: List[Dict[str, Any]] = []
        if os.path.exists(JOURNAL_FILE):
            try:
                with open(JOURNAL_FILE, "r") as f:
                    data = json.load(f)
            except Exception:
                data = []
        if date:
            data = [r for r in data if r.get("date") == date]
        if min_confidence:
            data = [r for r in data if (r.get("confidence") or 0) >= min_confidence]

        def stats(rows: List[Dict[str, Any]]) -> Dict[str, Any]:
            trades = [r for r in rows if r.get("result") != "NO_TRADE"]
            wins = [r for r in trades if r["result"] == "WIN"]
            losses = [r for r in trades if r["result"] == "LOSS"]
            return {
                "signals": len(rows),
                "trades_entered": len(trades),
                "no_trade": len(rows) - len(trades),
                "wins": len(wins),
                "losses": len(losses),
                "win_rate_pct": round(len(wins) / len(trades) * 100, 1) if trades else None,
                "total_pnl_amount": round(sum(r.get("pnl_amount", 0) for r in trades), 2),
                "avg_pnl_points": round(sum(r.get("pnl_points", 0) for r in trades) / len(trades), 2) if trades else 0.0,
            }

        open_signals = []
        with cls._lock:
            for st in cls._locks.values():
                if st["status"] in OPEN_STATES:
                    open_signals.append(cls._public(st, levels_locked=True))

        return {
            "status": "success",
            "overall": stats(data),
            "high_confidence_80_plus": stats([r for r in data if (r.get("confidence") or 0) >= 80]),
            "below_80": stats([r for r in data if (r.get("confidence") or 0) < 80]),
            "by_symbol": {s: stats([r for r in data if r["symbol"] == s]) for s in sorted({r["symbol"] for r in data})},
            "open_signals": open_signals,
            "recent": data[:50],
        }

    # ------------------------------------------------------------------ public view
    @classmethod
    def _public(cls, st: Dict[str, Any], levels_locked: bool, confirming: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        now = time.time()
        expires_at = st["locked_at"] + cls.MAX_LOCK_MINUTES * 60
        return {
            "id": st["id"],
            "status": st["status"],
            "status_text": STATUS_TEXT.get(st["status"], st["status"]),
            "is_open": st["status"] in OPEN_STATES,
            "direction": st["direction"],
            "symbol": st["symbol"],
            "timeframe": st["timeframe"],
            "contract": st.get("contract"),
            "strike": st.get("strike"),
            "option_type": st.get("option_type"),
            "entry": st["entry"],
            "stop_loss": st["sl"],
            "initial_stop_loss": st["sl_initial"],
            "target_1": st["t1"],
            "target_2": st["t2"],
            "last_ltp": st.get("last_ltp"),
            "exit_price": st.get("exit_price"),
            "confidence": st.get("confidence"),
            "confirmations": cls.CONFIRM_CANDLES,
            "entry_mode": st.get("entry_mode", "CONFIRMED"),
            "locked_at": cls._fmt(st["locked_at"]),
            "entered_at": cls._fmt(st.get("entered_at")),
            "t1_hit_at": cls._fmt(st.get("t1_hit_at")),
            "resolved_at": cls._fmt(st.get("resolved_at")),
            "expires_at": cls._fmt(expires_at),
            "minutes_left": max(0, int((expires_at - now) // 60)) if st["status"] in OPEN_STATES else 0,
            "levels_locked": levels_locked,
            "confirming": confirming,
        }

    @staticmethod
    def _apply_levels(raw: Dict[str, Any], st: Dict[str, Any]):
        te = raw.get("trade_execution") or {}
        lot = te.get("lot_size") or st.get("lot_size") or 1
        entry, sl, t1, t2 = st["entry"], st["sl"], st["t1"], st["t2"]
        risk = round(entry - st["sl_initial"], 2)
        te.update({
            "recommended_entry": entry,
            "stop_loss": sl,
            "target_1": t1,
            "target_2": t2,
            "risk_per_share": risk,
            "reward_target_1": round(t1 - entry, 1),
            "reward_target_2": round(t2 - entry, 1),
            "capital_required": round(lot * entry, 2),
            "max_risk_amount": round(lot * risk, 2),
            "target_1_profit": round(lot * (t1 - entry), 2),
            "target_2_profit": round(lot * (t2 - entry), 2),
            "risk_reward_ratio": f"1 : {round((t1 - entry) / max(0.1, risk), 1)}",
        })
        raw["trade_execution"] = te
        ltp = te.get("current_ltp", entry)
        raw["option_premium"] = {
            **(raw.get("option_premium") or {}),
            "buy_range": f"₹{round(min(ltp, entry) - 1.0, 1)} - ₹{entry}",
            "stop_loss": f"₹{sl}",
            "target_1": f"₹{t1}",
            "target_2": f"₹{t2}",
            "risk_points": f"₹{risk} pts",
            "reward_points": f"₹{round(t1 - entry, 1)} pts",
        }
        ea = raw.get("emergency_exit_alert")
        if isinstance(ea, dict):
            ea["stop_loss"] = sl
            ea["target_1"] = t1
            ea["current_ltp"] = ltp
            if st["status"] == "SL_HIT":
                ea.update({
                    "triggered": True,
                    "severity": "CRITICAL",
                    "type": "STOP_LOSS_HIT",
                    "title": "🛑 STOP LOSS HIT - EXIT",
                    "message": f"Locked signal stop loss ₹{sl} was hit. Exit the position.",
                    "action": "SELL / EXIT NOW",
                })
            elif ea.get("triggered") and ltp > sl and ea.get("type") != "STOP_LOSS_HIT":
                # Only the SL check is authoritative on locked levels; keep reversal warnings as-is.
                pass
        raw["generated_at"] = SignalLockService._fmt(st["locked_at"])
        raw["valid_until"] = SignalLockService._fmt(st["locked_at"] + SignalLockService.MAX_LOCK_MINUTES * 60)

    # ------------------------------------------------------------------ main
    @classmethod
    def evaluate(
        cls,
        indicator,
        candles: List[Dict[str, Any]],
        cmp: Optional[float] = None,
        symbol: Optional[str] = None,
        expiry_type: str = "current",
        selected_strike: Optional[int] = None,
        selected_option_type: Optional[str] = None,
        timeframe: str = "5m",
        custom_lot_size: Optional[int] = None,
    ) -> Dict[str, Any]:
        now = time.time()
        tf_key, tf_sec = cls._tf(timeframe)
        sym = cls._norm_symbol(symbol)
        key = f"{sym}|{tf_key}|{(expiry_type or 'current').strip().lower()}"

        base_kwargs = dict(
            cmp=cmp, symbol=symbol, expiry_type=expiry_type,
            timeframe=timeframe, custom_lot_size=custom_lot_size,
        )

        closed = cls._closed_candles(candles or [], tf_sec, now)
        if len(closed) < 16:
            # Not enough closed history: fall back to un-locked evaluation, but never trade on it
            raw = indicator._evaluate_raw_signal(
                candles, selected_strike=selected_strike, selected_option_type=selected_option_type,
                forced_direction="SIDEWAYS" if len(candles or []) >= 15 else None, **base_kwargs,
            )
            raw["signal_lock"] = None
            raw["signal_status"] = "NO_SIGNAL"
            return raw

        closed_time = closed[-1].get("time")
        s_now = indicator._evaluate_raw_signal(
            closed, score_only=True, score_price=closed[-1]["close"], **base_kwargs)
        s_prev = indicator._evaluate_raw_signal(
            closed[:-1], score_only=True, score_price=closed[-2]["close"], **base_kwargs)

        score_kwargs = dict(score_candles=closed, score_price=closed[-1]["close"])

        with cls._lock:
            st = cls._locks.get(key)
            st = dict(st) if st else None

        # ---------- 1. An OPEN locked signal exists -> keep it, track it
        if st and st["status"] in OPEN_STATES:
            weak = False
            if closed_time != st.get("last_checked_candle"):
                st["last_checked_candle"] = closed_time
                weak = cls._favour(s_now, st["direction"]) < cls.HOLD_GAP

            user_override = (
                (selected_strike and int(selected_strike) != st["strike"])
                or (selected_option_type and selected_option_type.upper().strip() != st["option_type"])
            )
            raw = indicator._evaluate_raw_signal(
                candles,
                selected_strike=selected_strike or st["strike"],
                selected_option_type=selected_option_type or st["option_type"],
                forced_direction=st["direction"],
                **score_kwargs, **base_kwargs,
            )
            if not user_override:
                ltp = float((raw.get("trade_execution") or {}).get("current_ltp") or 0.0)
                cls._advance(st, ltp, now, weak)
                if st["status"] not in OPEN_STATES:
                    st["resolved_candle"] = closed_time
                    cls._journal(st)
                with cls._lock:
                    cls._locks[key] = st

            if st["status"] in OPEN_STATES or user_override:
                if not user_override:
                    cls._apply_levels(raw, st)
                raw["signal_lock"] = cls._public(st, levels_locked=not user_override)
                raw["signal_status"] = st["status"]
                return raw

            # resolved just now -> show the result, no new direction this candle
            raw = indicator._evaluate_raw_signal(
                candles, selected_strike=selected_strike, selected_option_type=selected_option_type,
                forced_direction="SIDEWAYS", **score_kwargs, **base_kwargs,
            )
            raw["decision"] = f"WAIT - last signal closed ({STATUS_TEXT.get(st['status'], st['status'])})"
            raw["signal_lock"] = cls._public(st, levels_locked=False)
            raw["signal_status"] = st["status"]
            return raw

        # ---------- 2. Cool-down: a signal was resolved on this same closed candle
        if st and st.get("resolved_candle") == closed_time:
            raw = indicator._evaluate_raw_signal(
                candles, selected_strike=selected_strike, selected_option_type=selected_option_type,
                forced_direction="SIDEWAYS", **score_kwargs, **base_kwargs,
            )
            raw["decision"] = f"WAIT - last signal closed ({STATUS_TEXT.get(st['status'], st['status'])})"
            raw["signal_lock"] = cls._public(st, levels_locked=False)
            raw["signal_status"] = st["status"]
            return raw

        # ---------- 3. Look for a NEW signal
        #   CONFIRMED path: 2 closed candles agree (stable, slower)
        #   FAST path     : strong live move held for >= FAST_HOLD_SEC and not opposed by
        #                   the last closed candle (catches the moment, no candle-close wait)
        side_now = cls._side(s_now, cls.ENTER_GAP, cls.ENTER_PCT)
        side_prev = cls._side(s_prev, cls.ENTER_GAP, cls.ENTER_PCT)
        confirmed = bool(side_now and side_now == side_prev)

        fast_side = None
        if not confirmed:
            s_live = indicator._evaluate_raw_signal(
                candles, score_only=True, **base_kwargs)
            fast_side = cls._fast_trigger(key, s_live, s_now, now)
        else:
            cls._fast.pop(key, None)

        lock_side = side_now if confirmed else fast_side

        if lock_side:
            side_now = lock_side
            entry_mode = "CONFIRMED" if confirmed else "FAST_LIVE"
            raw = indicator._evaluate_raw_signal(
                candles, selected_strike=selected_strike, selected_option_type=selected_option_type,
                forced_direction=side_now, **score_kwargs, **base_kwargs,
            )
            te = raw.get("trade_execution") or {}
            new_st = {
                "id": f"{sym.replace(' ', '')}_{tf_key}_{side_now}_{int(closed_time or now)}",
                "key": key,
                "symbol": sym,
                "timeframe": tf_key,
                "direction": side_now,
                "strike": raw.get("selected_strike"),
                "option_type": raw.get("selected_option_type"),
                "contract": te.get("contract_name"),
                "tradingsymbol": te.get("tradingsymbol"),
                "lot_size": te.get("lot_size"),
                "entry": te.get("recommended_entry"),
                "sl": te.get("stop_loss"),
                "sl_initial": te.get("stop_loss"),
                "t1": te.get("target_1"),
                "t2": te.get("target_2"),
                "confidence": raw.get("confidence"),
                "status": "PENDING_ENTRY",
                "entry_mode": entry_mode,
                "locked_at": now,
                "locked_candle": closed_time,
                "last_checked_candle": closed_time,
                "last_ltp": te.get("current_ltp"),
            }
            if None in (new_st["entry"], new_st["sl"], new_st["t1"], new_st["t2"]):
                raw["signal_lock"] = None
                raw["signal_status"] = "NO_SIGNAL"
                return raw

            with cls._lock:
                existing = cls._locks.get(key)
                if existing and existing["status"] in OPEN_STATES:
                    new_st = dict(existing)  # another request locked first
                else:
                    cls._locks[key] = new_st
            cls._apply_levels(raw, new_st)
            raw["signal_lock"] = cls._public(new_st, levels_locked=True)
            raw["signal_status"] = new_st["status"]
            return raw

        # ---------- 4. No confirmed setup -> WAIT (show confirmation progress)
        raw = indicator._evaluate_raw_signal(
            candles, selected_strike=selected_strike, selected_option_type=selected_option_type,
            forced_direction="SIDEWAYS", **score_kwargs, **base_kwargs,
        )
        confirming = None
        if side_now:
            confirming = {
                "direction": side_now,
                "confirmed_candles": 1,
                "required_candles": cls.CONFIRM_CANDLES,
                "message": f"{side_now} building - 1/{cls.CONFIRM_CANDLES} closed candles confirmed. Wait for next candle close.",
            }
            raw["decision"] = f"WAIT - {side_now} needs 1 more closed candle"
        else:
            raw["decision"] = "WAIT / NO TRADE (No confirmed setup)"
        raw["signal_lock"] = cls._public(st, levels_locked=False) if st else None
        if raw["signal_lock"] is not None:
            raw["signal_lock"]["confirming"] = confirming
        raw["signal_confirming"] = confirming
        raw["signal_status"] = "CONFIRMING" if confirming else "NO_SIGNAL"
        return raw

