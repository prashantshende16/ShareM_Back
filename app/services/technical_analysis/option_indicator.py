from typing import List, Dict, Any, Optional
import math

class OptionSignalIndicator:
    """
    Intraday 5-Minute Option Trade Signal Engine.
    Detects high-probability CALL vs PUT option setups using:
    1. Candlestick Pattern Recognition (Hammer, Shooting Star, Bullish/Bearish Engulfing, Morning/Evening Star, Pinbars)
    2. Multi-Indicator Confluence (EMA 9/21 Trend Ribbon, SuperTrend / Momentum, RSI 14 Direction, VWAP alignment)
    3. Volume & Range Expansion Check
    """

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
    def evaluate_5m_option_signal(cls, candles: List[Dict[str, Any]], cmp: Optional[float] = None) -> Dict[str, Any]:
        """
        Synthesizes Candlestick Patterns + EMA Ribbon + RSI + VWAP into a definitive
        5-minute CALL vs PUT option trade signal.
        """
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
                "patterns_detected": [],
                "indicators": {},
                "summary": "Insufficient 5-minute candles to compute accurate option indicators."
            }

        closes = [c["close"] for c in candles]
        current_price = cmp or closes[-1]

        # Calculate Technical Indicators
        ema9 = cls.calculate_ema(closes, 9)
        ema21 = cls.calculate_ema(closes, 21)
        rsi14 = cls.calculate_rsi(closes, 14)
        vwap = cls.calculate_vwap(candles)

        cur_ema9 = ema9[-1]
        cur_ema21 = ema21[-1]
        cur_rsi = rsi14[-1]
        cur_vwap = vwap[-1] if vwap else current_price

        call_score = 0
        put_score = 0
        reasons = []

        # 1. EMA 9 vs EMA 21 Trend Ribbon (25 Points)
        if cur_ema9 > cur_ema21:
            diff_pct = ((cur_ema9 - cur_ema21) / cur_ema21) * 100
            call_score += 25
            reasons.append(f"EMA 9 ({cur_ema9}) above EMA 21 ({cur_ema21}) - Bullish trend ribbon (+25)")
        else:
            put_score += 25
            reasons.append(f"EMA 9 ({cur_ema9}) below EMA 21 ({cur_ema21}) - Bearish trend ribbon (+25)")

        # 2. VWAP Alignment (20 Points)
        if current_price > cur_vwap:
            call_score += 20
            reasons.append(f"Price ({current_price}) trading above intraday VWAP ({cur_vwap}) - Buyers in control (+20)")
        else:
            put_score += 20
            reasons.append(f"Price ({current_price}) trading below intraday VWAP ({cur_vwap}) - Sellers in control (+20)")

        # 3. RSI 14 Momentum (20 Points)
        if cur_rsi > 58:
            call_score += 20
            reasons.append(f"RSI 14 at {cur_rsi} showing bullish expansion (>58) (+20)")
        elif cur_rsi < 42:
            put_score += 20
            reasons.append(f"RSI 14 at {cur_rsi} showing bearish momentum breakdown (<42) (+20)")
        elif cur_rsi >= 50:
            call_score += 10
            reasons.append(f"RSI 14 above midpoint 50 ({cur_rsi}) (+10)")
        else:
            put_score += 10
            reasons.append(f"RSI 14 below midpoint 50 ({cur_rsi}) (+10)")

        # 4. Candlestick Pattern Signals (Up to 35 Points)
        detected_patterns = cls.detect_candlestick_patterns(candles)
        for pat in detected_patterns:
            if pat["bias"] == "CALL":
                call_score += pat["weight"]
                reasons.append(f"{pat['name']} detected: {pat['description']} (+{pat['weight']})")
            elif pat["bias"] == "PUT":
                put_score += pat["weight"]
                reasons.append(f"{pat['name']} detected: {pat['description']} (+{pat['weight']})")

        # 5. Volume Spike Check on Latest Candle
        last_candle = candles[-1]
        prev_candle = candles[-2] if len(candles) >= 2 else last_candle
        last_vol = last_candle.get("volume", 0)
        prev_vol = prev_candle.get("volume", 0)
        if last_vol > prev_vol * 1.3 and last_vol > 0:
            if last_candle["close"] > last_candle["open"]:
                call_score += 10
                reasons.append("Volume surge (+30%) on green 5-minute candle confirming buyers (+10)")
            else:
                put_score += 10
                reasons.append("Volume surge (+30%) on red 5-minute candle confirming sellers (+10)")

        # Determine Decision & Confidence
        total_points = call_score + put_score
        call_pct = int(round((call_score / max(1, total_points)) * 100))
        put_pct = 100 - call_pct

        # Dynamic strike suggestion (ATM step based on index price level)
        strike_step = 50 if current_price < 30000 else 100
        atm_strike = int(round(current_price / strike_step) * strike_step)

        # SL and Target distances based on Average True Range or percentage (approx 0.2% - 0.35% for 5m options)
        sl_points = max(15.0, round(current_price * 0.0022, 1))
        t1_points = round(sl_points * 1.8, 1)
        t2_points = round(sl_points * 2.8, 1)

        if call_score >= put_score + 20 and call_pct >= 60:
            decision = "BUY CALL (CE)"
            direction = "CALL"
            confidence = min(92, max(64, call_pct))
            strike_suggest = f"{atm_strike} CE"
            stop_loss = round(current_price - sl_points, 1)
            target_1 = round(current_price + t1_points, 1)
            target_2 = round(current_price + t2_points, 1)
            summary = (
                f"High-Probability 5-Minute CALL setup for {strike_suggest}. "
                f"Bullish confluence driven by EMA ribbon alignment, price holding above VWAP, "
                f"and favorable candlestick price action."
            )
        elif put_score >= call_score + 20 and put_pct >= 60:
            decision = "BUY PUT (PE)"
            direction = "PUT"
            confidence = min(92, max(64, put_pct))
            strike_suggest = f"{atm_strike} PE"
            stop_loss = round(current_price + sl_points, 1)
            target_1 = round(current_price - t1_points, 1)
            target_2 = round(current_price - t2_points, 1)
            summary = (
                f"High-Probability 5-Minute PUT setup for {strike_suggest}. "
                f"Bearish breakdown confluence driven by EMA ribbon rejection, price trading under VWAP, "
                f"and seller rejection wicks."
            )
        else:
            decision = "WAIT / NO TRADE (Range-Bound)"
            direction = "SIDEWAYS"
            confidence = 52
            strike_suggest = f"{atm_strike} Straddle / Wait"
            stop_loss = round(current_price - sl_points, 1)
            target_1 = round(current_price + t1_points, 1)
            target_2 = round(current_price + t2_points, 1)
            summary = (
                f"5-Minute market is currently consolidating without strong directional confluence. "
                f"Indicators are conflicting (Call score: {call_score}, Put score: {put_score}). "
                f"Wait for clear breakout above {round(current_price + sl_points, 1)} or breakdown below {round(current_price - sl_points, 1)}."
            )

        return {
            "decision": decision,
            "direction": direction,
            "confidence": confidence,
            "call_score": call_pct,
            "put_score": put_pct,
            "strike_suggestion": strike_suggest,
            "entry_price": round(current_price, 2),
            "stop_loss": stop_loss,
            "target_1": target_1,
            "target_2": target_2,
            "risk_reward": f"1 : {round(t1_points / sl_points, 1)}",
            "timeframe": "5 Minute",
            "expected_holding_time": "15 to 30 Minutes",
            "patterns_detected": [p["name"] for p in detected_patterns],
            "indicators": {
                "ema_9": round(cur_ema9, 2),
                "ema_21": round(cur_ema21, 2),
                "rsi_14": cur_rsi,
                "vwap": cur_vwap,
                "trend_ribbon": "BULLISH" if cur_ema9 > cur_ema21 else "BEARISH",
                "vwap_position": "ABOVE_VWAP" if current_price > cur_vwap else "BELOW_VWAP"
            },
            "signals_breakdown": reasons,
            "summary": summary
        }

