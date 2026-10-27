from typing import List, Dict, Any, Optional
import math
import time
import threading
import logging
from datetime import datetime, timedelta
import pytz

logger = logging.getLogger(__name__)

class OptionSignalIndicator:
    """
    Intraday Multi-Timeframe (5m, 15m, 30m, 1h) Option Trade Signal Engine.
    Detects high-probability CALL vs PUT option setups using:
    1. Candlestick Pattern Recognition (Hammer, Shooting Star, Bullish/Bearish Engulfing, Morning/Evening Star, Pinbars)
    2. Multi-Indicator Confluence (EMA 9/21/50/200 Ribbon, SuperTrend / Momentum, RSI 14 Direction, VWAP alignment)
    3. Anchored Trade Levels (Stabilizes Entry, SL, Target 1, Target 2 per timeframe slot to eliminate 30s jitter)
    4. Emergency Exit / Sudden Market Reversal Sentinel (Alerts user immediately to sell if market suddenly dumps/surges)
    """
    _anchored_setups: Dict[str, Dict[str, Any]] = {}
    _setup_lock = threading.Lock()

    @staticmethod
    def normal_cdf(x: float) -> float:
        """Standard normal cumulative distribution function."""
        return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))

    @classmethod
    def calculate_delta(cls, spot: float, strike: float, dte: int, iv: float = 0.18, is_call: bool = True) -> float:
        """
        Calculates Black-Scholes Delta for European/NSE Index Options.
        Returns Delta between 0.05 and 0.95 (positive for Call, negative for Put).
        """
        try:
            t = max(0.002, dte / 365.0)
            v = max(0.05, iv)
            r = 0.07  # 7% repo interest rate proxy
            d1 = (math.log(spot / strike) + (r + 0.5 * v * v) * t) / (v * math.sqrt(t))
            delta = cls.normal_cdf(d1)
            if not is_call:
                delta = delta - 1.0
            return round(delta, 2)
        except Exception:
            diff = spot - strike
            base = 0.50 + (diff / (spot * 0.02)) * 0.25
            base = max(0.05, min(0.95, base))
            return round(base if is_call else (base - 1.0), 2)

    @staticmethod
    def calculate_ema(prices: List[float], period: int) -> List[float]:
        if len(prices) < period:
            return [prices[-1]] * len(prices) if prices else []
        multiplier = 2 / (period + 1)
        ema_values = [sum(prices[:period]) / period]
        for p in prices[period:]:
            new_ema = (p - ema_values[-1]) * multiplier + ema_values[-1]
            ema_values.append(new_ema)
        # Pad beginning
        prefix = [prices[0]] * (len(prices) - len(ema_values))
        return prefix + ema_values

    @staticmethod
    def calculate_rsi(prices: List[float], period: int = 14) -> List[float]:
        if len(prices) <= period:
            return [50.0] * len(prices)
        deltas = [prices[i] - prices[i - 1] for i in range(1, len(prices))]
        gains = [d if d > 0 else 0.0 for d in deltas]
        losses = [-d if d < 0 else 0.0 for d in deltas]

        avg_gain = sum(gains[:period]) / period
        avg_loss = sum(losses[:period]) / period

        rsi_list = [50.0] * period
        rs = avg_gain / avg_loss if avg_loss != 0 else 100.0
        rsi_list.append(round(100.0 - (100.0 / (1.0 + rs)), 1))

        for i in range(period, len(deltas)):
            avg_gain = (avg_gain * (period - 1) + gains[i]) / period
            avg_loss = (avg_loss * (period - 1) + losses[i]) / period
            if avg_loss == 0:
                rsi_val = 100.0
            else:
                rs = avg_gain / avg_loss
                rsi_val = round(100.0 - (100.0 / (1.0 + rs)), 1)
            rsi_list.append(rsi_val)

        return rsi_list

    @staticmethod
    def calculate_vwap(candles: List[Dict[str, Any]]) -> List[float]:
        vwap_list = []
        cum_pv = 0.0
        cum_vol = 0.0
        for c in candles:
            typical_price = (c["high"] + c["low"] + c["close"]) / 3.0
            vol = max(1.0, float(c.get("volume", 1)))
            cum_pv += typical_price * vol
            cum_vol += vol
            vwap_list.append(round(cum_pv / cum_vol, 2))
        return vwap_list

    @staticmethod
    def calculate_atr(candles: List[Dict[str, Any]], period: int = 14) -> List[float]:
        if len(candles) < 2:
            return [10.0] * len(candles)
        tr_list = []
        for i in range(len(candles)):
            if i == 0:
                tr_list.append(candles[i]["high"] - candles[i]["low"])
            else:
                h = candles[i]["high"]
                l = candles[i]["low"]
                cp = candles[i - 1]["close"]
                tr = max(h - l, abs(h - cp), abs(l - cp))
                tr_list.append(tr)
        atr_list = []
        for i in range(len(tr_list)):
            if i < period:
                atr_list.append(sum(tr_list[:i + 1]) / (i + 1))
            else:
                atr_list.append((atr_list[-1] * (period - 1) + tr_list[i]) / period)
        return [round(x, 2) for x in atr_list]

    @classmethod
    def calculate_supertrend(cls, candles: List[Dict[str, Any]], period: int = 10, multiplier: float = 3.0) -> Dict[str, Any]:
        if len(candles) < period + 1:
            return {"trend": "NEUTRAL", "value": candles[-1]["close"] if candles else 0.0, "atr": 10.0}
        atr_vals = cls.calculate_atr(candles, period)
        hl2 = (candles[-1]["high"] + candles[-1]["low"]) / 2.0
        cur_atr = atr_vals[-1]
        cur_close = candles[-1]["close"]
        upper_band = hl2 + (multiplier * cur_atr)
        lower_band = hl2 - (multiplier * cur_atr)
        trend = "BULLISH" if cur_close > lower_band else "BEARISH"
        return {
            "trend": trend,
            "upper_band": round(upper_band, 2),
            "lower_band": round(lower_band, 2),
            "atr": cur_atr
        }

    @classmethod
    def calculate_macd(cls, prices: List[float], fast: int = 12, slow: int = 26, signal: int = 9) -> Dict[str, Any]:
        if len(prices) < slow:
            return {"macd": 0.0, "signal": 0.0, "hist": 0.0, "trend": "NEUTRAL", "status": "NEUTRAL", "is_bull_cross": False, "is_bear_cross": False}
        ema_fast = cls.calculate_ema(prices, fast)
        ema_slow = cls.calculate_ema(prices, slow)
        macd_line = [f - s for f, s in zip(ema_fast, ema_slow)]
        signal_line = cls.calculate_ema(macd_line, signal)
        hist = [m - s for m, s in zip(macd_line, signal_line)]

        cur_macd = round(macd_line[-1], 2)
        cur_sig = round(signal_line[-1], 2)
        cur_hist = round(hist[-1], 2)
        prev_hist = round(hist[-2], 2) if len(hist) >= 2 else cur_hist

        is_bull_cross = (cur_macd > cur_sig) and (len(macd_line) >= 2 and macd_line[-2] <= signal_line[-2])
        is_bear_cross = (cur_macd < cur_sig) and (len(macd_line) >= 2 and macd_line[-2] >= signal_line[-2])
        trend = "BULLISH" if cur_macd > cur_sig else "BEARISH"

        return {
            "macd": cur_macd,
            "signal": cur_sig,
            "hist": cur_hist,
            "trend": trend,
            "is_bull_cross": is_bull_cross,
            "is_bear_cross": is_bear_cross,
            "expanding": abs(cur_hist) > abs(prev_hist)
        }

    @staticmethod
    def calculate_bollinger_bands(prices: List[float], period: int = 20, num_std: float = 2.0) -> Dict[str, Any]:
        if len(prices) < period:
            cmp = prices[-1] if prices else 0.0
            return {"upper": cmp, "middle": cmp, "lower": cmp, "bandwidth": 0.0, "percent_b": 0.5, "is_squeeze": False}
        window = prices[-period:]
        sma = sum(window) / period
        variance = sum((x - sma) ** 2 for x in window) / period
        std_dev = math.sqrt(variance)
        upper = sma + (num_std * std_dev)
        lower = sma - (num_std * std_dev)
        cmp = prices[-1]
        bw = round(((upper - lower) / max(0.01, sma)) * 100, 2)
        pb = round((cmp - lower) / max(0.01, upper - lower), 2)
        return {
            "upper": round(upper, 2),
            "middle": round(sma, 2),
            "lower": round(lower, 2),
            "bandwidth": bw,
            "percent_b": pb,
            "is_squeeze": bw < 2.0
        }

    @staticmethod
    def calculate_cpr_pivots(candles: List[Dict[str, Any]]) -> Dict[str, Any]:
        """
        Calculates Central Pivot Range (CPR) and classic R1/R2/S1/S2 levels.
        Uses prior candle session range (or last 20 candles if intraday continuous).
        """
        if not candles or len(candles) < 5:
            cmp = candles[-1]["close"] if candles else 0.0
            return {"pivot": cmp, "tc": cmp, "bc": cmp, "r1": cmp, "s1": cmp, "cpr_width": "NORMAL", "position": "AT_PIVOT"}

        sample = candles[-25:-1] if len(candles) >= 26 else candles[:-1]
        if not sample:
            sample = candles
        high = max(c["high"] for c in sample)
        low = min(c["low"] for c in sample)
        close = sample[-1]["close"]
        cmp = candles[-1]["close"]

        p = round((high + low + close) / 3.0, 2)
        bc = round((high + low) / 2.0, 2)
        tc = round((p - bc) + p, 2)

        top_c = max(tc, bc)
        bot_c = min(tc, bc)

        r1 = round((2 * p) - low, 2)
        s1 = round((2 * p) - high, 2)
        r2 = round(p + (high - low), 2)
        s2 = round(p - (high - low), 2)

        cpr_width_pts = round(top_c - bot_c, 2)
        cpr_width_pct = round((cpr_width_pts / max(0.01, p)) * 100, 3)
        width_tag = "NARROW (Trending Potential)" if cpr_width_pct < 0.15 else "WIDE (Sideways Potential)" if cpr_width_pct > 0.45 else "AVERAGE"

        if cmp > top_c:
            pos = "ABOVE_CPR (Bullish)"
        elif cmp < bot_c:
            pos = "BELOW_CPR (Bearish)"
        else:
            pos = "INSIDE_CPR (Neutral Range)"

        return {
            "pivot": p,
            "tc": top_c,
            "bc": bot_c,
            "r1": r1,
            "s1": s1,
            "r2": r2,
            "s2": s2,
            "cpr_width": width_tag,
            "cpr_width_pts": cpr_width_pts,
            "position": pos
        }

    @classmethod
    def detect_candlestick_patterns(cls, candles: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """
        Analyzes the last 1 to 3 candles to detect actionable intraday 5-min patterns.
        """
        if len(candles) < 3:
            return []

        patterns = []
        c1 = candles[-1] # current / latest
        c2 = candles[-2] # previous
        c3 = candles[-3] # 2 bars ago

        c1_body = abs(c1["close"] - c1["open"])
        c1_range = max(0.01, c1["high"] - c1["low"])
        c1_upper_wick = c1["high"] - max(c1["close"], c1["open"])
        c1_lower_wick = min(c1["close"], c1["open"]) - c1["low"]
        c1_is_bull = c1["close"] > c1["open"]

        c2_body = abs(c2["close"] - c2["open"])
        c2_range = max(0.01, c2["high"] - c2["low"])
        c2_is_bull = c2["close"] > c2["open"]

        # 1. Bullish Hammer (Lower shadow >= 2x body, tiny upper shadow, close near high)
        if c1_lower_wick >= (1.8 * c1_body) and c1_upper_wick <= (0.25 * c1_range) and c1_range > 0:
            patterns.append({
                "name": "Bullish Hammer Pinbar",
                "bias": "CALL",
                "weight": 28,
                "description": "Strong buyer defense wick rejecting lower levels within 5 min."
            })

        # 2. Shooting Star / Inverted Pinbar (Upper shadow >= 2x body, tiny lower shadow)
        if c1_upper_wick >= (1.8 * c1_body) and c1_lower_wick <= (0.25 * c1_range) and c1_range > 0:
            patterns.append({
                "name": "Shooting Star / Bearish Pinbar",
                "bias": "PUT",
                "weight": 28,
                "description": "Aggressive seller rejection wick from overhead resistance within 5 min."
            })

        # 3. Bullish Engulfing
        if not c2_is_bull and c1_is_bull and c1["close"] > c2["open"] and c1["open"] <= c2["close"] and c1_body > c2_body:
            patterns.append({
                "name": "Bullish Engulfing Pattern",
                "bias": "CALL",
                "weight": 32,
                "description": "5-Min green candle completely engulfs prior red body, indicating aggressive call buying."
            })

        # 4. Bearish Engulfing
        if c2_is_bull and not c1_is_bull and c1["close"] < c2["open"] and c1["open"] >= c2["close"] and c1_body > c2_body:
            patterns.append({
                "name": "Bearish Engulfing Pattern",
                "bias": "PUT",
                "weight": 32,
                "description": "5-Min red candle completely engulfs prior green body, indicating aggressive put buying."
            })

        # 5. Morning Star Reversal (c3 red, c2 small body/doji, c1 strong green)
        if not c3["close"] > c3["open"] and (c2_body / max(0.01, c2_range) < 0.35) and c1_is_bull and c1["close"] > (c3["open"] + c3["close"]) / 2:
            patterns.append({
                "name": "Morning Star 3-Bar Reversal",
                "bias": "CALL",
                "weight": 30,
                "description": "High-accuracy 3-candle reversal at intraday support."
            })

        # 6. Evening Star Reversal (c3 green, c2 small body/doji, c1 strong red)
        if c3["close"] > c3["open"] and (c2_body / max(0.01, c2_range) < 0.35) and not c1_is_bull and c1["close"] < (c3["open"] + c3["close"]) / 2:
            patterns.append({
                "name": "Evening Star 3-Bar Reversal",
                "bias": "PUT",
                "weight": 30,
                "description": "High-accuracy 3-candle reversal at intraday resistance."
            })

        # 7. 3-Bar Momentum Breakout
        if c1_is_bull and c2_is_bull and c3["close"] > c3["open"] and c1["close"] > c2["close"] > c3["close"]:
            patterns.append({
                "name": "Three White Soldiers (Momentum Continuation)",
                "bias": "CALL",
                "weight": 22,
                "description": "Consecutive expanding green bars showing continuous intraday buying pressure."
            })
        elif not c1_is_bull and not c2_is_bull and not (c3["close"] > c3["open"]) and c1["close"] < c2["close"] < c3["close"]:
            patterns.append({
                "name": "Three Black Crows (Breakdown Momentum)",
                "bias": "PUT",
                "weight": 22,
                "description": "Consecutive expanding red bars breaking lower swing levels."
            })

        return patterns

    @classmethod
    def get_expiry_dates(cls, symbol: Optional[str] = None) -> Dict[str, Any]:
        """
        Calculates all upcoming Indian market derivatives expiry dates across NSE & BSE:
        - NIFTY 50 / BANK NIFTY: Weekly & Monthly (Thursday / Tuesday)
        - 16 Oct 2026: User requested / immediate contract (Friday / BSE Sensex)
        - FINNIFTY: Tuesday
        - MIDCPNIFTY: Monday (e.g. 19 Oct Dussehra rescheduled)
        - Monthly: Last Thursday of month
        """
        try:
            ist = pytz.timezone("Asia/Kolkata")
            now_ist = datetime.now(ist)
        except Exception:
            now_ist = datetime.utcnow()

        today = now_ist.date()
        sym = (symbol or "NIFTY 50").strip().upper()

        # 1. Official Real Exchange Expiries directly from Angel One scrip master
        try:
            real_expiries = AngelOneService.get_real_expiries_sync(sym)
            if real_expiries:
                current_expiry = real_expiries[0]["date"]
                next_expiry = real_expiries[1]["date"] if len(real_expiries) > 1 else current_expiry
                is_today = (real_expiries[0]["dte"] == 0)
                return {
                    "current_expiry": current_expiry,
                    "next_expiry": next_expiry,
                    "is_today_expiry": is_today,
                    "available_expiries": real_expiries
                }
        except Exception as e:
            logger.warning(f"Could not fetch real expiries from Angel One for {sym}: {e}")

        available_expiries = []
        dates_set = set()

        # 1. Today is only active 0DTE if today matches the exchange weekly expiry for this symbol
        is_symbol_expiry_today = (
            ("SENSEX" in sym and today.weekday() == 4) or
            ("MID" in sym and today.weekday() == 0) or
            ("FIN" in sym and today.weekday() == 1) or
            ("BANK" in sym and today.weekday() in (1, 2, 3)) or
            ("NIFTY" in sym and today.weekday() in (1, 3))
        )
        is_market_trading = (now_ist.hour < 15 or (now_ist.hour == 15 and now_ist.minute < 30))
        if is_market_trading and is_symbol_expiry_today:
            today_str = today.strftime("%d %b %Y")
            dates_set.add(today_str)
            available_expiries.append({
                "id": today_str,
                "type": "today",
                "date": today_str,
                "label": f"{today.strftime('%d %b')} (Today / 0DTE)",
                "tag": "0DTE",
                "dte": 0
            })

        # 2. Specifically ensure 16 Oct 2026 is present (Friday / User requested active expiry)
        target_16 = datetime(2026, 10, 16).date()
        str_16 = target_16.strftime("%d %b %Y")
        if str_16 not in dates_set and target_16 >= today:
            dates_set.add(str_16)
            dte_16 = (target_16 - today).days
            available_expiries.append({
                "id": str_16,
                "type": "16-oct",
                "date": str_16,
                "label": f"{str_16} (Friday)",
                "tag": "16 Oct",
                "dte": dte_16
            })

        # 3. Comprehensive Indian Market Expiries for next 5 weeks
        # Checks Thursday (Nifty/BankNifty/Monthly), Monday (Midcap/Rescheduled), Tuesday (FinNifty), Friday (Sensex)
        for day_offset in range(1, 36):
            d = today + timedelta(days=day_offset)
            d_str = d.strftime("%d %b %Y")
            if d_str in dates_set:
                continue

            # Thursday: Nifty 50, Bank Nifty, and Monthly Expiries
            if d.weekday() == 3:
                dates_set.add(d_str)
                next_thurs = d + timedelta(days=7)
                is_monthly = (next_thurs.month != d.month)
                tag = "Monthly" if is_monthly else "Weekly"
                available_expiries.append({
                    "id": d_str,
                    "type": "monthly" if is_monthly else "weekly",
                    "date": d_str,
                    "label": f"{d_str} ({tag})",
                    "tag": tag,
                    "dte": day_offset
                })
            # Monday: Midcap Nifty & Holiday-Rescheduled Expiries (e.g. Dussehra 19 Oct)
            elif d.weekday() == 0 and day_offset <= 14:
                dates_set.add(d_str)
                available_expiries.append({
                    "id": d_str,
                    "type": "midcap",
                    "date": d_str,
                    "label": f"{d_str} (Monday)",
                    "tag": "Midcap",
                    "dte": day_offset
                })
            # Tuesday: Nifty 50, FinNifty, Bank Nifty
            elif d.weekday() == 1:
                dates_set.add(d_str)
                available_expiries.append({
                    "id": d_str,
                    "type": "weekly",
                    "date": d_str,
                    "label": f"{d_str} (Tuesday)",
                    "tag": "Weekly",
                    "dte": day_offset
                })
            # Friday: BSE Sensex
            elif d.weekday() == 4 and "SENSEX" in sym:
                dates_set.add(d_str)
                available_expiries.append({
                    "id": d_str,
                    "type": "sensex",
                    "date": d_str,
                    "label": f"{d_str} (Friday)",
                    "tag": "Sensex",
                    "dte": day_offset
                })

        available_expiries.sort(key=lambda x: x["dte"])

        current_expiry = available_expiries[0]["date"] if available_expiries else today.strftime("%d %b %Y")
        # Next primary contract (e.g. 16 Oct or next weekly)
        next_expiry = str_16 if str_16 in dates_set and str_16 != current_expiry else (
            available_expiries[1]["date"] if len(available_expiries) > 1 else current_expiry
        )
        is_today = (available_expiries[0]["dte"] == 0) if available_expiries else False

        return {
            "current_expiry": current_expiry,
            "next_expiry": next_expiry,
            "is_today_expiry": is_today,
            "available_expiries": available_expiries
        }

    @classmethod
    def evaluate_5m_option_signal(
        cls,
        candles: List[Dict[str, Any]],
        cmp: Optional[float] = None,
        symbol: Optional[str] = None,
        expiry_type: str = "current",
        selected_strike: Optional[int] = None,
        selected_option_type: Optional[str] = None,
        timeframe: str = "5m",
        custom_lot_size: Optional[int] = None
    ) -> Dict[str, Any]:
        """
        Synthesizes Candlestick Patterns + EMA Ribbon (9/21/50/200) + RSI + VWAP +
        MACD + Bollinger Bands + CPR Pivots + SuperTrend into an institutional
        intraday option trade signal for 5-minute or 15-minute durations.
        """
        tf_clean = str(timeframe or "5m").strip().lower()
        is_1h = tf_clean in ["1h", "60m", "60", "1 hour"]
        is_30m = tf_clean in ["30m", "30", "30min", "30 minute"]
        is_15m = tf_clean in ["15m", "15", "15min", "15 minute"]

        if is_1h:
            tf_label = "1-Hour"
            tf_hold = "2 to 4 Hours"
            valid_duration_mins = 120
            slot_duration = 3600
        elif is_30m:
            tf_label = "30-Minute"
            tf_hold = "1 to 2 Hours"
            valid_duration_mins = 60
            slot_duration = 1800
        elif is_15m:
            tf_label = "15-Minute"
            tf_hold = "30 to 60 Minutes"
            valid_duration_mins = 45
            slot_duration = 900
        else:
            tf_label = "5-Minute"
            tf_hold = "15 to 30 Minutes"
            valid_duration_mins = 30
            slot_duration = 300

        if not candles or len(candles) < 15:
            return {
                "decision": "WAIT / NO TRADE",
                "direction": "NEUTRAL",
                "confidence": 50,
                "call_score": 50,
                "put_score": 50,
                "strike_suggestion": "ATM",
                "entry_price": round(cmp, 2) if cmp else 0.0,
                "stop_loss": 0.0,
                "target_1": 0.0,
                "target_2": 0.0,
                "risk_reward": "1:2.0",
                "timeframe": tf_label,
                "expected_holding_time": tf_hold,
                "patterns_detected": [],
                "indicators": {},
                "summary": f"Insufficient {tf_label} candles to compute accurate option indicators."
            }

        closes = [c["close"] for c in candles]
        current_price = cmp or closes[-1]

        # Calculate Technical Indicator Suite
        ema9 = cls.calculate_ema(closes, 9)
        ema21 = cls.calculate_ema(closes, 21)
        ema50 = cls.calculate_ema(closes, 50)
        ema200 = cls.calculate_ema(closes, 200)
        rsi14 = cls.calculate_rsi(closes, 14)
        vwap = cls.calculate_vwap(candles)
        macd = cls.calculate_macd(closes)
        bb = cls.calculate_bollinger_bands(closes)
        cpr = cls.calculate_cpr_pivots(candles)
        supertrend = cls.calculate_supertrend(candles)

        cur_ema9 = ema9[-1]
        cur_ema21 = ema21[-1]
        cur_ema50 = ema50[-1]
        cur_ema200 = ema200[-1]
        cur_rsi = rsi14[-1]
        cur_vwap = vwap[-1] if vwap else current_price

        call_score = 0
        put_score = 0
        reasons = []

        # 1. EMA 9 vs EMA 21 Trend Ribbon (20 Points)
        if cur_ema9 > cur_ema21:
            diff_pct = round(((cur_ema9 - cur_ema21) / cur_ema21) * 100, 2)
            call_score += 20
            reasons.append(f"EMA 9 ({cur_ema9}) above EMA 21 ({cur_ema21}) - Bullish trend ribbon (+20)")
        else:
            put_score += 20
            reasons.append(f"EMA 9 ({cur_ema9}) below EMA 21 ({cur_ema21}) - Bearish trend ribbon (+20)")

        # 2. EMA 50 / 200 Long-Term Alignment (15 Points)
        if current_price > cur_ema50 and cur_ema50 > cur_ema200:
            call_score += 15
            reasons.append(f"Price & EMA 50 ({cur_ema50}) above EMA 200 ({cur_ema200}) - Golden long-term trend (+15)")
        elif current_price < cur_ema50 and cur_ema50 < cur_ema200:
            put_score += 15
            reasons.append(f"Price & EMA 50 ({cur_ema50}) below EMA 200 ({cur_ema200}) - Death cross / Bear trend (+15)")
        elif current_price > cur_ema50:
            call_score += 8
            reasons.append(f"Price above 50 EMA ({cur_ema50}) (+8)")
        else:
            put_score += 8
            reasons.append(f"Price below 50 EMA ({cur_ema50}) (+8)")

        # 3. VWAP Alignment (20 Points)
        if current_price > cur_vwap:
            call_score += 20
            reasons.append(f"Price ({current_price}) trading above intraday VWAP ({cur_vwap}) - Buyers in control (+20)")
        else:
            put_score += 20
            reasons.append(f"Price ({current_price}) trading below intraday VWAP ({cur_vwap}) - Sellers in control (+20)")

        # 4. RSI 14 Momentum (15 Points)
        if cur_rsi > 58:
            call_score += 15
            reasons.append(f"RSI 14 at {cur_rsi} showing bullish expansion (>58) (+15)")
        elif cur_rsi < 42:
            put_score += 15
            reasons.append(f"RSI 14 at {cur_rsi} showing bearish momentum breakdown (<42) (+15)")
        elif cur_rsi >= 50:
            call_score += 8
            reasons.append(f"RSI 14 above midpoint 50 ({cur_rsi}) (+8)")
        else:
            put_score += 8
            reasons.append(f"RSI 14 below midpoint 50 ({cur_rsi}) (+8)")

        # 5. MACD (12, 26, 9) Crossover & Histogram (15 Points)
        if macd.get("trend") == "BULLISH":
            call_score += 15
            reasons.append(f"MACD line ({macd.get('macd')}) above Signal ({macd.get('signal')}) with {'Bullish Crossover' if macd.get('is_bull_cross') else 'Positive Histogram'} (+15)")
        else:
            put_score += 15
            reasons.append(f"MACD line ({macd.get('macd')}) below Signal ({macd.get('signal')}) with {'Bearish Crossover' if macd.get('is_bear_cross') else 'Negative Histogram'} (+15)")

        # 6. Bollinger Bands (20, 2) Position & Squeeze (10 Points)
        if bb.get("percent_b", 0.5) > 0.6:
            call_score += 10
            reasons.append(f"Bollinger %B ({bb.get('percent_b')}) pushing upper band ({bb.get('upper')}) (+10)")
        elif bb.get("percent_b", 0.5) < 0.4:
            put_score += 10
            reasons.append(f"Bollinger %B ({bb.get('percent_b')}) pressing lower band ({bb.get('lower')}) (+10)")

        # 7. Central Pivot Range (CPR) Position (15 Points)
        if cpr.get("position", "").startswith("ABOVE_CPR"):
            call_score += 15
            reasons.append(f"Price trading above Central Pivot Range (TC: {cpr.get('tc')}, Pivot: {cpr.get('pivot')}) - Bullish (+15)")
        elif cpr.get("position", "").startswith("BELOW_CPR"):
            put_score += 15
            reasons.append(f"Price trading below Central Pivot Range (BC: {cpr.get('bc')}, Pivot: {cpr.get('pivot')}) - Bearish (+15)")
        else:
            reasons.append(f"Price inside Central Pivot Range (TC: {cpr.get('tc')}, BC: {cpr.get('bc')}) - Neutral range consolidation")

        # 8. Candlestick Pattern Signals (Up to 30 Points)
        detected_patterns = cls.detect_candlestick_patterns(candles)
        for pat in detected_patterns:
            if pat["bias"] == "CALL":
                call_score += pat["weight"]
                reasons.append(f"{pat['name']} detected on {tf_label}: {pat['description']} (+{pat['weight']})")
            elif pat["bias"] == "PUT":
                put_score += pat["weight"]
                reasons.append(f"{pat['name']} detected on {tf_label}: {pat['description']} (+{pat['weight']})")

        # 9. Volume Spike Check on Latest Candle
        last_candle = candles[-1]
        prev_candle = candles[-2] if len(candles) >= 2 else last_candle
        last_vol = last_candle.get("volume", 0)
        prev_vol = prev_candle.get("volume", 0)
        if last_vol > prev_vol * 1.3 and last_vol > 0:
            if last_candle["close"] > last_candle["open"]:
                call_score += 10
                reasons.append(f"Volume surge (+30%) on green {tf_label} candle confirming buyers (+10)")
            else:
                put_score += 10
                reasons.append(f"Volume surge (+30%) on red {tf_label} candle confirming sellers (+10)")

        # Determine Decision & Confidence
        total_points = call_score + put_score
        call_pct = int(round((call_score / max(1, total_points)) * 100))
        put_pct = 100 - call_pct

        # Dynamic strike suggestion (ATM step based on index price level)
        strike_step = 50 if current_price < 30000 else 100
        atm_strike = int(round(current_price / strike_step) * strike_step)

        # SL and Target distances on Index Spot (approx 0.2% - 0.35% for 5m options)
        sl_points = max(15.0, round(current_price * 0.0022, 1))
        t1_points = round(sl_points * 1.8, 1)
        t2_points = round(sl_points * 2.8, 1)

        # -------------------------------------------------------------
        # OPTION PREMIUM ESTIMATION (In Rupees ₹, what is bought on broker)
        # Using Delta ~ 0.50 (ATM) and average weekly ATM volatility/theta
        # -------------------------------------------------------------
        delta = 0.52  # Standard ATM delta
        # Typical ATM base premium proportional to index spot price (~0.55% of spot)
        # e.g., ~125 for Nifty (22.7k), ~280 for BankNifty (51k), ~410 for Sensex (74k)
        base_prem = round(max(30.0, current_price * 0.0055), 1)

        try:
            ist = pytz.timezone("Asia/Kolkata")
            now_ist = datetime.now(ist)
        except Exception:
            now_ist = datetime.utcnow()

        # Multi-expiry resolution
        expiry_info = cls.get_expiry_dates(symbol)
        available = expiry_info["available_expiries"]

        # Resolve selected expiry from request parameter
        req = (expiry_type or "current").strip()
        active_exp_obj = None

        # 1. Direct or partial match against available dates / ids / tags
        for exp in available:
            if req.lower() in exp["date"].lower() or req.lower() == exp["id"].lower() or req.lower() == exp.get("type", "").lower() or req.lower() == exp.get("tag", "").lower():
                active_exp_obj = exp
                break

        # 2. Check "16" specifically (user's requested 16 Oct 2026 expiry)
        if not active_exp_obj and "16" in req:
            for exp in available:
                if "16" in exp["date"]:
                    active_exp_obj = exp
                    break

        # 3. Check "next"
        if not active_exp_obj and "next" in req.lower():
            active_exp_obj = available[1] if len(available) > 1 else (available[0] if available else None)

        # 4. Check "current" or "today"
        if not active_exp_obj:
            active_exp_obj = available[0] if available else {
                "id": now_ist.strftime("%d %b %Y"),
                "date": now_ist.strftime("%d %b %Y"),
                "label": now_ist.strftime("%d %b %Y"),
                "tag": "Current",
                "dte": 0
            }

        active_expiry_str = active_exp_obj["date"]
        active_dte = active_exp_obj.get("dte", 0)
        active_label = active_exp_obj.get("label", active_expiry_str)

        # Scaled time value / theta multiplier based on exact Days To Expiry (DTE)
        if active_dte == 0:
            time_mult = 1.0
        elif active_dte == 1:
            time_mult = 1.10
        elif active_dte <= 4:
            time_mult = 1.25
        elif active_dte <= 7:
            time_mult = 1.35
        elif active_dte <= 14:
            time_mult = 1.55
        elif active_dte <= 21:
            time_mult = 1.70
        else:
            time_mult = 1.85

        # Exchange Lot Sizes (Updated: SENSEX 1 Lot = 20 Qty, BANK NIFTY 1 Lot = 60 Qty)
        LOT_SIZES = {
            "SENSEX": 20,
            "^BSESN": 20,
            "BANK NIFTY": 60,
            "BANKNIFTY": 60,
            "^NSEBANK": 60,
            "NIFTY 50": 65,
            "NIFTY": 65,
            "^NSEI": 65,
            "FINNIFTY": 65,
            "MIDCPNIFTY": 75
        }
        sym_clean = (symbol or "NIFTY 50").strip().upper()
        if custom_lot_size and custom_lot_size > 0:
            lot_size = custom_lot_size
        else:
            lot_size = 65
            for k, v in LOT_SIZES.items():
                if k in sym_clean or sym_clean in k:
                    lot_size = v
                    break

        # Calculate SuperTrend & Volatility
        supertrend = cls.calculate_supertrend(candles)

        # 1. Determine Decision & Direction
        if call_score >= put_score + 20 and call_pct >= 60:
            decision = "BUY CALL (CE)"
            direction = "CALL"
            confidence = min(92, max(64, call_pct))
            default_opt_type = "CE"
            default_strike = atm_strike
            stop_loss = round(current_price - sl_points, 1)
            target_1 = round(current_price + t1_points, 1)
            target_2 = round(current_price + t2_points, 1)
        elif put_score >= call_score + 20 and put_pct >= 60:
            decision = "BUY PUT (PE)"
            direction = "PUT"
            confidence = min(92, max(64, put_pct))
            default_opt_type = "PE"
            default_strike = atm_strike
            stop_loss = round(current_price + sl_points, 1)
            target_1 = round(current_price - t1_points, 1)
            target_2 = round(current_price - t2_points, 1)
        else:
            decision = "WAIT / NO TRADE (Range-Bound)"
            direction = "SIDEWAYS"
            confidence = 52
            default_opt_type = "CE"
            default_strike = atm_strike
            stop_loss = round(current_price - sl_points, 1)
            target_1 = round(current_price + t1_points, 1)
            target_2 = round(current_price + t2_points, 1)

        # Resolve selected strike or default
        target_strike = int(selected_strike) if selected_strike else default_strike
        target_opt_type = (selected_option_type or default_opt_type).upper().strip()
        strike_suggest = f"{target_strike} {target_opt_type}"

        # Build Interactive Strike List around ATM for UI selection (-5 to +5 steps)
        available_strikes = []
        for i in range(-5, 6):
            s_val = atm_strike + (i * strike_step)
            diff = s_val - atm_strike
            if diff == 0:
                s_tag = "ATM"
            elif (target_opt_type == "CE" and diff < 0) or (target_opt_type == "PE" and diff > 0):
                s_tag = f"ITM {abs(diff)}"
            else:
                s_tag = f"OTM {abs(diff)}"

            stk_delta = cls.calculate_delta(
                spot=current_price,
                strike=s_val,
                dte=active_dte,
                iv=0.18,
                is_call=(target_opt_type == "CE")
            )

            available_strikes.append({
                "strike": s_val,
                "label": f"{s_val} ({s_tag})",
                "tag": s_tag,
                "delta": stk_delta,
                "is_atm": diff == 0,
                "is_selected": s_val == target_strike
            })

        # Calculate Intrinsic Value for the target strike
        if target_opt_type == "CE":
            intrinsic = max(0.0, current_price - target_strike)
        else:
            intrinsic = max(0.0, target_strike - current_price)

        # 2. Try fetching REAL LIVE OPTION QUOTE from Angel One SmartAPI
        live_option_quote = None
        try:
            from app.services.market_data.angel_one_service import AngelOneService
            if AngelOneService.is_configured():
                live_option_quote = AngelOneService.get_option_quote_sync(
                    underlying=sym_clean,
                    expiry_str=active_expiry_str,
                    strike=target_strike,
                    option_type=target_opt_type
                )
        except Exception as e:
            logger.warning(f"Could not fetch Angel One option quote for {sym_clean} {target_strike} {target_opt_type}: {e}")

        is_live_angel_one = False
        real_high = 0.0
        real_low = 0.0
        real_close = 0.0
        real_open = 0.0
        contract_tradingsymbol = ""
        contract_symboltoken = ""

        if live_option_quote and live_option_quote.get("ltp", 0.0) > 0:
            # REAL LIVE MARKET DATA FROM ANGEL ONE (0-Second Delay)
            prem_ltp = round(float(live_option_quote["ltp"]), 1)
            real_close = round(float(live_option_quote.get("close", 0.0)), 1)
            real_high = round(float(live_option_quote.get("high", 0.0)), 1)
            real_low = round(float(live_option_quote.get("low", 0.0)), 1)
            real_open = round(float(live_option_quote.get("open", 0.0)), 1)
            contract_tradingsymbol = live_option_quote.get("tradingsymbol", "")
            contract_symboltoken = str(live_option_quote.get("symboltoken", ""))
            is_live_angel_one = True
        else:
            # FALLBACK SYNTHETIC BLACK-SCHOLES/INTRINSIC HEURISTIC
            if active_dte == 0:
                hour_ist = now_ist.hour if hasattr(now_ist, 'hour') else 12
                decay = 0.60 if hour_ist >= 14 else (0.75 if hour_ist >= 12 else 1.0)
                time_val = base_prem * 0.55 * decay
            elif active_dte == 1:
                time_val = base_prem * 0.85
            elif active_dte <= 4:
                time_val = base_prem * 1.15
            elif active_dte <= 7:
                time_val = base_prem * 1.35
            else:
                time_val = base_prem * time_mult

            if intrinsic > 0:
                compression = max(0.20, 1.0 - (intrinsic / max(100.0, current_price * 0.015)))
                time_val = time_val * compression
            elif (target_opt_type == "CE" and target_strike > current_price) or (target_opt_type == "PE" and target_strike < current_price):
                dist = abs(current_price - target_strike)
                otm_factor = math.exp(-0.5 * (dist / max(10.0, time_val * 1.2)) ** 2)
                time_val = max(5.0, time_val * otm_factor)

            prem_ltp = round(max(5.0, intrinsic + time_val), 1)

        # -------------------------------------------------------------
        # ANCHORED SETUP STABILIZER (Eliminates 30-Second Target & SL Jitter)
        # Keeps Trigger Entry, Stop Loss, Target 1, Target 2 rock solid during candle slot
        # -------------------------------------------------------------
        cur_epoch = time.time()
        slot_id = int(cur_epoch // slot_duration)
        setup_cache_key = f"{sym_clean}_{active_expiry_str}_{target_strike}_{target_opt_type}_{tf_clean}_{slot_id}"

        cached_setup = None
        with cls._setup_lock:
            cached_setup = cls._anchored_setups.get(setup_cache_key)

        if cached_setup and direction == cached_setup.get("direction"):
            # REUSE STABLE ANCHORED LEVELS — Target & SL DO NOT MOVE on 30s ticks!
            prem_entry = cached_setup["entry"]
            prem_sl = cached_setup["sl"]
            prem_t1 = cached_setup["t1"]
            prem_t2 = cached_setup["t2"]
            entry_buffer = cached_setup.get("entry_buffer", round(max(1.0, prem_entry - prem_ltp), 1))
        else:
            # First time in candle slot: Calculate high R:R targets with tight loss limit
            sl_pct = 0.10 if is_1h else (0.11 if is_30m else 0.12)
            t1_mult = 2.8 if is_1h else (2.5 if is_30m else 2.4)
            t2_mult = 4.5 if is_1h else (4.0 if is_30m else 3.8)

            entry_buffer = round(max(2.0, min(15.0, prem_ltp * 0.035)), 1)
            prem_entry = round(prem_ltp + entry_buffer, 1)

            # Minimal loss rule: tight structural SL
            prem_sl_pts = round(max(3.0, min(60.0, prem_entry * sl_pct)), 1)
            prem_sl = round(max(1.0, prem_entry - prem_sl_pts), 1)

            # Big momentum move (equivalent to 100 to 150 points index expansion)
            prem_t1 = round(prem_entry + (prem_sl_pts * t1_mult), 1)
            prem_t2 = round(prem_entry + (prem_sl_pts * t2_mult), 1)

            with cls._setup_lock:
                cls._anchored_setups[setup_cache_key] = {
                    "entry": prem_entry,
                    "sl": prem_sl,
                    "t1": prem_t1,
                    "t2": prem_t2,
                    "entry_buffer": entry_buffer,
                    "anchor_ltp": prem_ltp,
                    "direction": direction,
                    "created_at": cur_epoch,
                    "slot_id": slot_id
                }

        # Clean old setup cache (keep memory compact)
        if len(cls._anchored_setups) > 100:
            with cls._setup_lock:
                old_keys = [k for k, v in cls._anchored_setups.items() if (cur_epoch - v.get("created_at", 0)) > 7200]
                for k in old_keys:
                    cls._anchored_setups.pop(k, None)

        prem_entry_low = round(prem_ltp - 1.0, 1)
        prem_entry_high = prem_entry

        # -------------------------------------------------------------
        # EMERGENCY REVERSAL & SUDDEN DOWNFALL / SURGE ALERT ENGINE
        # Immediately detects if market reverses against trade within 1-2 mins
        # -------------------------------------------------------------
        emergency_exit_alert = {
            "triggered": False,
            "severity": "NORMAL",
            "type": "NONE",
            "title": "",
            "message": "",
            "reason": "",
            "action": "HOLD_MONITOR",
            "contract": contract_tradingsymbol or f"{sym_clean} {strike_suggest}",
            "current_ltp": prem_ltp,
            "stop_loss": prem_sl,
            "target_1": prem_t1,
            "triggered_at": None
        }

        # Check Sudden Downfall / Breakdown against CALL:
        if direction == "CALL":
            hit_sl = prem_ltp <= prem_sl
            vwap_breakdown = current_price < (cur_vwap - max(8.0, current_price * 0.0008))
            sharp_red_candle = (
                len(candles) >= 2
                and (candles[-1]["close"] < candles[-1]["open"])
                and ((candles[-1]["open"] - candles[-1]["close"]) > max(10.0, current_price * 0.0012))
            )

            if hit_sl or (vwap_breakdown and sharp_red_candle):
                emergency_exit_alert["triggered"] = True
                emergency_exit_alert["severity"] = "CRITICAL"
                emergency_exit_alert["type"] = "SUDDEN_DOWNFALL_REVERSAL"
                emergency_exit_alert["title"] = "🚨 EMERGENCY EXIT: SUDDEN MARKET DOWNFALL!"
                emergency_exit_alert["message"] = (
                    f"WARNING: Sudden sharp market downfall detected on {sym_clean}! "
                    f"Price broke below VWAP (₹{round(cur_vwap, 1)}) with aggressive selling. "
                    f"SELL / EXIT {strike_suggest} immediately to prevent rapid capital loss!"
                )
                emergency_exit_alert["reason"] = (
                    f"Stop Loss breached (LTP ₹{prem_ltp} <= SL ₹{prem_sl}). Immediate loss mitigation required."
                    if hit_sl else f"Sudden high-volume bearish breakdown below VWAP ({round(cur_vwap, 1)}). Immediate cut recommended."
                )
                emergency_exit_alert["action"] = "SELL / EXIT NOW"
                emergency_exit_alert["triggered_at"] = now_ist.strftime("%I:%M:%S %p")

        # Check Sudden Upsurge / Breakdown against PUT:
        elif direction == "PUT":
            hit_sl = prem_ltp <= prem_sl
            vwap_breakout = current_price > (cur_vwap + max(8.0, current_price * 0.0008))
            sharp_green_candle = (
                len(candles) >= 2
                and (candles[-1]["close"] > candles[-1]["open"])
                and ((candles[-1]["close"] - candles[-1]["open"]) > max(10.0, current_price * 0.0012))
            )

            if hit_sl or (vwap_breakout and sharp_green_candle):
                emergency_exit_alert["triggered"] = True
                emergency_exit_alert["severity"] = "CRITICAL"
                emergency_exit_alert["type"] = "SUDDEN_SURGE_REVERSAL"
                emergency_exit_alert["title"] = "🚨 EMERGENCY EXIT: SUDDEN MARKET SURGE!"
                emergency_exit_alert["message"] = (
                    f"WARNING: Sudden sharp upward market surge detected on {sym_clean}! "
                    f"Price spiked above VWAP (₹{round(cur_vwap, 1)}) with aggressive buying. "
                    f"SELL / EXIT {strike_suggest} immediately to prevent rapid capital loss!"
                )
                emergency_exit_alert["reason"] = (
                    f"Stop Loss breached (LTP ₹{prem_ltp} <= SL ₹{prem_sl}). Immediate loss mitigation required."
                    if hit_sl else f"Sudden high-volume bullish breakout above VWAP ({round(cur_vwap, 1)}). Immediate cut recommended."
                )
                emergency_exit_alert["action"] = "SELL / EXIT NOW"
                emergency_exit_alert["triggered_at"] = now_ist.strftime("%I:%M:%S %p")

        # Generate contextual trade summary
        if direction == "CALL":
            summary = (
                f"High-Probability {tf_label} CALL setup for {sym_clean} {active_expiry_str} {strike_suggest}. "
                f"LTP: ₹{prem_ltp}. Recommended Buy Entry above ₹{prem_entry} (SL: ₹{prem_sl}, T1: ₹{prem_t1}, T2: ₹{prem_t2}). "
                f"Requires ₹{round(lot_size * prem_entry, 2)} capital per lot ({lot_size} qty)."
            )
        elif direction == "PUT":
            summary = (
                f"High-Probability {tf_label} PUT setup for {sym_clean} {active_expiry_str} {strike_suggest}. "
                f"LTP: ₹{prem_ltp}. Recommended Buy Entry above ₹{prem_entry} (SL: ₹{prem_sl}, T1: ₹{prem_t1}, T2: ₹{prem_t2}). "
                f"Requires ₹{round(lot_size * prem_entry, 2)} capital per lot ({lot_size} qty)."
            )
        else:
            summary = (
                f"{tf_label} market is currently consolidating without strong directional confluence. "
                f"Indicators are conflicting (Call: {call_score}, Put: {put_score}). "
                f"Wait for clear breakout above {round(current_price + sl_points, 1)} or breakdown below {round(current_price - sl_points, 1)}."
            )

        # -------------------------------------------------------------
        # 10-INDICATOR CONFLUENCE CHECKLIST (High-Accuracy Observation Matrix)
        # -------------------------------------------------------------
        # 1. EMA 9 / 21 Trend Ribbon
        ema_bias = "CALL" if cur_ema9 > cur_ema21 else "PUT"
        ema_confirmed = (ema_bias == direction)
        ind_1 = {
            "id": 1,
            "name": "EMA 9 / 21 Trend Ribbon",
            "bias": ema_bias,
            "status": "CONFIRMED" if ema_confirmed else "CONFLICT",
            "value": f"EMA9: {round(cur_ema9, 2)} | EMA21: {round(cur_ema21, 2)}",
            "description": f"EMA 9 is trading {'above' if ema_bias == 'CALL' else 'below'} EMA 21 ({'Bullish Ribbon' if ema_bias == 'CALL' else 'Bearish Ribbon'})"
        }

        # 2. EMA 50 / 200 Long-Term Trend
        ema50_200_bias = "CALL" if current_price > cur_ema50 and cur_ema50 > cur_ema200 else ("PUT" if current_price < cur_ema50 and cur_ema50 < cur_ema200 else ("CALL" if current_price > cur_ema50 else "PUT"))
        ema50_200_confirmed = (ema50_200_bias == direction)
        ind_2 = {
            "id": 2,
            "name": "EMA 50 / 200 Trend Filter",
            "bias": ema50_200_bias,
            "status": "CONFIRMED" if ema50_200_confirmed else "CONFLICT",
            "value": f"EMA50: {round(cur_ema50, 1)} | EMA200: {round(cur_ema200, 1)}",
            "description": f"Price is trading {'above 50/200 EMA (Structural Bullish)' if ema50_200_bias == 'CALL' else 'below 50/200 EMA (Structural Bearish)'}"
        }

        # 3. Intraday VWAP Position
        vwap_bias = "CALL" if current_price > cur_vwap else "PUT"
        vwap_confirmed = (vwap_bias == direction)
        ind_3 = {
            "id": 3,
            "name": "Intraday VWAP Alignment",
            "bias": vwap_bias,
            "status": "CONFIRMED" if vwap_confirmed else "CONFLICT",
            "value": f"Spot: {round(current_price, 1)} | VWAP: {cur_vwap}",
            "description": f"Price is trading {'above VWAP (Buyers in command)' if vwap_bias == 'CALL' else 'below VWAP (Sellers in command)'}"
        }

        # 4. RSI 14 Momentum
        if cur_rsi >= 54:
            rsi_bias = "CALL"
        elif cur_rsi <= 46:
            rsi_bias = "PUT"
        else:
            rsi_bias = "NEUTRAL"
        rsi_confirmed = (rsi_bias == direction)
        ind_4 = {
            "id": 4,
            "name": "RSI 14 Momentum",
            "bias": rsi_bias,
            "status": "CONFIRMED" if rsi_confirmed else ("NEUTRAL" if rsi_bias == "NEUTRAL" else "CONFLICT"),
            "value": f"RSI: {cur_rsi}",
            "description": f"RSI at {cur_rsi} showing {'Bullish expansion (>54)' if rsi_bias == 'CALL' else 'Bearish breakdown (<46)' if rsi_bias == 'PUT' else 'Consolidation'}"
        }

        # 5. MACD (12, 26, 9) Histogram & Crossover
        macd_bias = "CALL" if macd.get("trend") == "BULLISH" else "PUT"
        macd_confirmed = (macd_bias == direction)
        ind_5 = {
            "id": 5,
            "name": "MACD (12, 26, 9) Momentum",
            "bias": macd_bias,
            "status": "CONFIRMED" if macd_confirmed else "CONFLICT",
            "value": f"MACD: {macd.get('macd')} | Sig: {macd.get('signal')} | Hist: {macd.get('hist')}",
            "description": f"MACD is {macd_bias} with {'Bullish Cross' if macd.get('is_bull_cross') else 'Bearish Cross' if macd.get('is_bear_cross') else ('Expanding Histogram' if macd.get('expanding') else 'Neutral Flow')}"
        }

        # 6. Bollinger Bands (20, 2) Position & Squeeze
        bb_pct = bb.get("percent_b", 0.5)
        bb_bias = "CALL" if bb_pct > 0.55 else ("PUT" if bb_pct < 0.45 else "NEUTRAL")
        bb_confirmed = (bb_bias == direction)
        ind_6 = {
            "id": 6,
            "name": "Bollinger Bands (20, 2)",
            "bias": bb_bias,
            "status": "CONFIRMED" if bb_confirmed else "NEUTRAL",
            "value": f"%B: {bb_pct} | BW: {bb.get('bandwidth')}%",
            "description": f"{'Volatility Squeeze - Ready for breakout' if bb.get('is_squeeze') else ('Expanding along Upper Band' if bb_bias == 'CALL' else 'Testing Lower Band' if bb_bias == 'PUT' else 'Within Middle Band')}"
        }

        # 7. Central Pivot Range (CPR) & Classic Levels
        cpr_pos = cpr.get("position", "")
        cpr_bias = "CALL" if cpr_pos.startswith("ABOVE") else ("PUT" if cpr_pos.startswith("BELOW") else "NEUTRAL")
        cpr_confirmed = (cpr_bias == direction)
        ind_7 = {
            "id": 7,
            "name": "CPR Pivot Boundary",
            "bias": cpr_bias,
            "status": "CONFIRMED" if cpr_confirmed else "NEUTRAL",
            "value": f"TC: {cpr.get('tc')} | P: {cpr.get('pivot')} | BC: {cpr.get('bc')}",
            "description": f"Price is {cpr_pos} ({cpr.get('cpr_width')})"
        }

        # 8. SuperTrend (10, 3) / ATR Trailing Band
        st_trend = supertrend.get("trend", "NEUTRAL")
        st_bias = "CALL" if st_trend == "BULLISH" else "PUT"
        st_confirmed = (st_bias == direction)
        ind_8 = {
            "id": 8,
            "name": "SuperTrend (10, 3) / ATR Trail",
            "bias": st_bias,
            "status": "CONFIRMED" if st_confirmed else "CONFLICT",
            "value": f"ATR: {supertrend.get('atr', 0)} pts | Level: {supertrend.get('lower_band' if st_bias == 'CALL' else 'upper_band', 0)}",
            "description": f"SuperTrend is {st_bias} ({'Price above trailing support' if st_bias == 'CALL' else 'Price below trailing resistance'})"
        }

        # 9. Candlestick Price Action
        pat_bias = detected_patterns[0]["bias"] if detected_patterns else "NEUTRAL"
        pat_confirmed = (pat_bias == direction)
        ind_9 = {
            "id": 9,
            "name": f"{tf_label} Candlestick Pattern",
            "bias": pat_bias,
            "status": "CONFIRMED" if pat_confirmed else "NEUTRAL",
            "value": detected_patterns[0]["name"] if detected_patterns else "Consolidation Bar",
            "description": detected_patterns[0]["description"] if detected_patterns else f"Price holding normal {tf_label} range"
        }

        # 10. Volume Expansion & Surge Filter
        is_vol_surge = (last_vol > prev_vol * 1.25 and last_vol > 0)
        vol_candle_bull = (last_candle["close"] > last_candle["open"])
        vol_bias = ("CALL" if vol_candle_bull else "PUT") if is_vol_surge else "NEUTRAL"
        vol_confirmed = (vol_bias == direction)
        ind_10 = {
            "id": 10,
            "name": "Volume Surge Filter",
            "bias": vol_bias,
            "status": "CONFIRMED" if vol_confirmed else "NEUTRAL",
            "value": f"Vol: {last_vol:,}" if last_vol > 0 else "Normal Volume",
            "description": f"Volume surged +25% on {tf_label} trigger candle" if is_vol_surge else "Standard volume flow"
        }

        indicator_checklist = [ind_1, ind_2, ind_3, ind_4, ind_5, ind_6, ind_7, ind_8, ind_9, ind_10]
        confirmed_count = sum(1 for ind in indicator_checklist if ind["status"] == "CONFIRMED")
        confluence_pct = int(round((confirmed_count / 10.0) * 100))
        verdict = (
            "STRONG CONFLUENCE (High Probability Setup)" if confirmed_count >= 8
            else "GOOD CONFLUENCE (Tradeable Setup)" if confirmed_count >= 6
            else "MODERATE CONFLUENCE (Caution / Wait)" if confirmed_count >= 4
            else "WEAK CONFLUENCE (Consolidation)"
        )
        confluence_score = {
            "confirmed": confirmed_count,
            "total": 10,
            "percentage": confluence_pct,
            "verdict": verdict
        }

        # Trade Execution Details & Lot/Capital Math
        capital_required = round(lot_size * prem_entry, 2)
        risk_per_share = round(prem_entry - prem_sl, 2)
        max_risk_amount = round(lot_size * risk_per_share, 2)
        target_1_profit = round(lot_size * (prem_t1 - prem_entry), 2)
        target_2_profit = round(lot_size * (prem_t2 - prem_entry), 2)
        contract_name = f"{contract_tradingsymbol + ' - ' if contract_tradingsymbol else ''}{sym_clean} {active_expiry_str.upper()} {strike_suggest}"
        target_delta = cls.calculate_delta(
            spot=current_price,
            strike=target_strike,
            dte=active_dte,
            iv=0.18,
            is_call=(target_opt_type == "CE")
        )

        trade_execution = {
            "contract_name": contract_name,
            "symbol": sym_clean,
            "expiry": active_expiry_str,
            "strike": strike_suggest,
            "delta": target_delta,
            "lot_size": lot_size,
            "lots": 1,
            "total_quantity": lot_size,
            "current_ltp": prem_ltp,
            "recommended_entry": prem_entry,
            "stop_loss": prem_sl,
            "target_1": prem_t1,
            "target_2": prem_t2,
            "risk_per_share": risk_per_share,
            "reward_target_1": round(prem_t1 - prem_entry, 1),
            "reward_target_2": round(prem_t2 - prem_entry, 1),
            "capital_required": capital_required,
            "max_risk_amount": max_risk_amount,
            "target_1_profit": target_1_profit,
            "target_2_profit": target_2_profit,
            "risk_reward_ratio": f"1 : {round((prem_t1 - prem_entry) / max(0.1, risk_per_share), 1)}",
            "is_live_angel_one": is_live_angel_one,
            "day_high": real_high,
            "day_low": real_low,
            "day_close": real_close,
            "day_open": real_open,
            "tradingsymbol": contract_tradingsymbol,
            "symboltoken": contract_symboltoken
        }

        generated_at_str = now_ist.strftime("%I:%M:%S %p")
        generated_at_iso = now_ist.isoformat()
        valid_until_dt = now_ist + timedelta(minutes=valid_duration_mins)
        valid_until_str = valid_until_dt.strftime("%I:%M:%S %p")

        # Extract last candle timestamp if available
        last_candle_epoch = candles[-1].get("time") if candles else None
        last_candle_time_str = None
        if last_candle_epoch:
            try:
                c_dt = datetime.fromtimestamp(last_candle_epoch, tz=pytz.timezone("Asia/Kolkata"))
                last_candle_time_str = c_dt.strftime("%I:%M %p")
            except Exception:
                pass

        # Build comprehensive expiries_data dictionary for all available dates
        expiries_data = {}
        for exp in available:
            d_dte = exp.get("dte", 0)
            if d_dte == 0:
                t_mult = 1.0
            elif d_dte == 1:
                t_mult = 1.10
            elif d_dte <= 4:
                t_mult = 1.25
            elif d_dte <= 7:
                t_mult = 1.35
            elif d_dte <= 14:
                t_mult = 1.55
            elif d_dte <= 21:
                t_mult = 1.70
            else:
                t_mult = 1.85

            e_t_mult = (
                0.55 if d_dte == 0
                else 0.85 if d_dte == 1
                else 1.15 if d_dte <= 4
                else 1.35 if d_dte <= 7
                else t_mult
            )
            e_ltp = round(max(5.0, intrinsic + (base_prem * e_t_mult)), 1)
            e_buf = round(max(2.5, min(25.0, e_ltp * 0.04)), 1)
            e_entry = round(e_ltp + e_buf, 1)
            e_sl_pts = round(max(6.0, min(80.0, e_entry * (0.25 if is_15m else 0.20))), 1)
            e_sl = max(3.0, round(e_entry - e_sl_pts, 1))
            e_t1 = round(e_entry + (e_sl_pts * (1.6 if is_15m else 1.4)), 1)
            e_t2 = round(e_entry + (e_sl_pts * (3.0 if is_15m else 2.8)), 1)

            entry_dict = {
                "expiry": exp["date"],
                "label": exp["label"],
                "tag": exp.get("tag", ""),
                "dte": d_dte,
                "buy_range": f"₹{e_ltp} - ₹{e_entry}",
                "stop_loss": f"₹{e_sl}",
                "target_1": f"₹{e_t1}",
                "target_2": f"₹{e_t2}",
                "risk_points": f"₹{e_sl_pts} pts",
                "reward_points": f"₹{round(e_t1 - e_entry, 1)} pts"
            }
            expiries_data[exp["date"]] = entry_dict
            expiries_data[exp["id"]] = entry_dict

        # Backward compatible keys
        if available:
            expiries_data["current"] = expiries_data.get(available[0]["date"], {})
            if len(available) > 1:
                expiries_data["next"] = expiries_data.get(available[1]["date"], {})

        return {
            "decision": decision,
            "direction": direction,
            "confidence": confidence,
            "call_score": call_pct,
            "put_score": put_pct,
            "strike_suggestion": strike_suggest,
            "active_expiry": active_expiry_str,
            "active_expiry_type": active_exp_obj.get("id", expiry_type),
            "active_expiry_label": active_label,
            "current_expiry": expiry_info["current_expiry"],
            "next_expiry": expiry_info["next_expiry"],
            "is_today_expiry": expiry_info["is_today_expiry"],
            "available_expiries": expiry_info["available_expiries"],
            "available_strikes": available_strikes,
            "selected_strike": target_strike,
            "selected_option_type": target_opt_type,
            "contract_tradingsymbol": contract_tradingsymbol,
            "contract_symboltoken": contract_symboltoken,
            "is_live_angel_one": is_live_angel_one,
            # Emergency Exit & Sudden Market Reversal Sentinel
            "emergency_exit_alert": emergency_exit_alert,
            # Detailed Trade Execution (Lot Size, Capital, Max Risk)
            "trade_execution": trade_execution,
            # 10-Indicator Observation Checklist
            "indicator_checklist": indicator_checklist,
            "confluence_score": confluence_score,
            # Option Premium (₹ Rupees Price traded on broker)
            "option_premium": {
                "buy_range": f"₹{prem_entry_low} - ₹{prem_entry_high}",
                "stop_loss": f"₹{prem_sl}",
                "target_1": f"₹{prem_t1}",
                "target_2": f"₹{prem_t2}",
                "risk_points": f"₹{risk_per_share} pts",
                "reward_points": f"₹{round(prem_t1 - prem_entry, 1)} pts"
            },
            "expiries_data": expiries_data,
            # Underlying Index Spot Levels (Point pivots on chart)
            "index_spot": {
                "cmp": round(current_price, 2),
                "entry_zone": f"{round(current_price - 12, 1)} - {round(current_price + 12, 1)}",
                "stop_loss": stop_loss,
                "target_1": target_1,
                "target_2": target_2,
                "risk_points": sl_points,
                "target_points": t1_points
            },
            "entry_price": round(current_price, 2),
            "stop_loss": stop_loss,
            "target_1": target_1,
            "target_2": target_2,
            "risk_reward": f"1 : {round(t1_points / sl_points, 1)}",
            "timeframe": tf_label,
            "expected_holding_time": tf_hold,
            "generated_at": generated_at_str,
            "generated_at_iso": generated_at_iso,
            "valid_until": valid_until_str,
            "last_candle_time": last_candle_time_str or generated_at_str,
            "patterns_detected": [p["name"] for p in detected_patterns],
            "indicators": {
                "ema_9": round(cur_ema9, 2),
                "ema_21": round(cur_ema21, 2),
                "ema_50": round(cur_ema50, 2),
                "ema_200": round(cur_ema200, 2),
                "rsi_14": cur_rsi,
                "vwap": cur_vwap,
                "macd": macd,
                "bollinger": bb,
                "cpr": cpr,
                "supertrend": supertrend.get("trend"),
                "trend_ribbon": "BULLISH" if cur_ema9 > cur_ema21 else "BEARISH",
                "vwap_position": "ABOVE_VWAP" if current_price > cur_vwap else "BELOW_VWAP"
            },
            "signals_breakdown": reasons,
            "summary": summary
        }

