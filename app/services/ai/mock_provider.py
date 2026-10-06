import os
import random
from typing import List, Dict, Any, Optional
from app.services.ai.base import AIVisionProvider

class MockProvider(AIVisionProvider):
    """
    Intelligent simulated Technical Analysis Vision Provider.
    Extracts basic image metadata and synthesizes realistic, probabilistic F&O market scenarios.
    Useful for local development, automated testing, and demonstration without live LLM billing.
    """
    async def analyze_chart(
        self,
        image_paths: List[str],
        timeframes: List[str],
        symbol: str,
        market_info: Dict[str, Any],
        notes: Optional[str] = None
    ) -> Dict[str, Any]:
        # Determine anchor price
        cmp = market_info.get("current_price")
        if not cmp:
            # Default reference prices for common symbols
            sym_upper = symbol.upper()
            if "BANKNIFTY" in sym_upper:
                cmp = 51250.0
            elif "FINNIFTY" in sym_upper:
                cmp = 23800.0
            elif "SENSEX" in sym_upper:
                cmp = 81500.0
            elif "RELIANCE" in sym_upper:
                cmp = 2950.0
            elif "TCS" in sym_upper:
                cmp = 4200.0
            elif "INFY" in sym_upper:
                cmp = 1880.0
            else:
                cmp = 25050.0  # NIFTY default

        # Calculate rounded step based on symbol
        step = 50.0 if cmp > 10000 else 10.0
        r1 = round((cmp + step * 1.5) / 10) * 10
        r2 = round((cmp + step * 3.2) / 10) * 10
        r3 = round((cmp + step * 5.0) / 10) * 10
        s1 = round((cmp - step * 1.5) / 10) * 10
        s2 = round((cmp - step * 3.0) / 10) * 10
        s3 = round((cmp - step * 4.8) / 10) * 10

        # Note-based context adjustments if provided
        notes_lower = (notes or "").lower()
        is_bullish_bias = "support" in notes_lower or "gap-up" in notes_lower or "call" in notes_lower or "long" in notes_lower
        is_bearish_bias = "resistance" in notes_lower or "breakdown" in notes_lower or "put" in notes_lower or "short" in notes_lower

        if is_bearish_bias and not is_bullish_bias:
            bull_prob = 22
            bear_prob = 68
            side_prob = 10
            primary = "bearish"
            trend = "Bearish"
            structure = "Lower High + Lower Low"
            setup_direction = "PUT"
            entry_zone = f"{cmp} - {cmp + step * 0.4:.1f}"
            stop_loss = f"{r1}"
            target_1 = f"{s1}"
            target_2 = f"{s2}"
            bias_summary = "Distribution structure detected below key intraday moving averages."
        elif is_bullish_bias and not is_bearish_bias:
            bull_prob = 72
            bear_prob = 18
            side_prob = 10
            primary = "bullish"
            trend = "Bullish"
            structure = "Higher High + Higher Low"
            setup_direction = "CALL"
            entry_zone = f"{cmp - step * 0.2:.1f} - {cmp + step * 0.3:.1f}"
            stop_loss = f"{s1}"
            target_1 = f"{r1}"
            target_2 = f"{r2}"
            bias_summary = "Accumulation base and upward channel expansion observed."
        else:
            # Balanced probability
            bull_prob = 68
            bear_prob = 22
            side_prob = 10
            primary = "bullish"
            trend = "Bullish"
            structure = "Higher High + Higher Low"
            setup_direction = "CALL"
            entry_zone = f"{cmp:.1f} - {cmp + step * 0.5:.1f}"
            stop_loss = f"{s1}"
            target_1 = f"{r1}"
            target_2 = f"{r2}"
            bias_summary = "Constructive consolidation near swing highs with volume absorption."

        # Multi-timeframe synthesis
        primary_tf = timeframes[0] if timeframes else "15 Minute"
        has_multi = len(timeframes) > 1

        pcr = market_info.get("pcr") or 1.15
        vix = market_info.get("india_vix") or 13.8

        return {
            "trend": trend,
            "primary_scenario": primary,
            "confidence_score": 74,
            "market_structure": {
                "trend": trend,
                "structure": structure,
                "momentum": "Strong" if bull_prob > 60 or bear_prob > 60 else "Moderate",
                "volatility": "Normal (VIX ~ " + str(vix) + ")",
                "liquidity": "High across benchmark strikes"
            },
            "support_levels": [
                {"label": "Support 1 (S1)", "price": s1, "strength": "Strong", "description": "Immediate swing support & VWAP base"},
                {"label": "Support 2 (S2)", "price": s2, "strength": "Major", "description": "Prior day value area low"},
                {"label": "Support 3 (S3)", "price": s3, "strength": "Weekly", "description": "Key demand zone"}
            ],
            "resistance_levels": [
                {"label": "Resistance 1 (R1)", "price": r1, "strength": "Strong", "description": "Recent pivot high & Call OI cluster"},
                {"label": "Resistance 2 (R2)", "price": r2, "strength": "Key", "description": "Daily breakout hurdle"},
                {"label": "Resistance 3 (R3)", "price": r3, "strength": "Major", "description": "Fibonacci extension 1.618"}
            ],
            "candlestick_analysis": {
                "patterns_detected": [
                    "Bullish Hammer near value area low",
                    "Three-bar continuation pattern on primary timeframe"
                ],
                "observation": "Rejection wicks visible from lower support levels, showing buyers defending dips."
            },
            "volume_analysis": {
                "trend": "Expanding on momentum waves",
                "observation": "Above-average volume recorded during upward pushes; volume dry-up observed on pullbacks."
            },
            "oi_analysis": {
                "pcr_reading": str(pcr),
                "observation": f"PCR at {pcr} indicates steady Put writing cushion around {s1} strike."
            },
            "technical_indicators": {
                "moving_averages": "Price holding above 20 EMA and 50 SMA across intraday charts",
                "rsi": "58.4 - Bullish momentum zone without overbought exhaustion",
                "vwap": "Price trading constructively above Session VWAP"
            },
            "scenarios": [
                {
                    "type": "bullish",
                    "probability": bull_prob,
                    "trigger": f"Sustained 5M candle close above {cmp + step * 0.5:.1f}",
                    "confirmation": "Expansion in green volume candles and RSI sustaining above 60",
                    "potential_movement": f"{cmp:.1f} → {r1} (Target 1), then {r2} (Target 2)",
                    "expected_range": f"{s1} - {r2}",
                    "invalidation": f"15M candle close below key support {s1}",
                    "time_horizon": "15-60 Minutes",
                    "risk_level": "Medium"
                },
                {
                    "type": "bearish",
                    "probability": bear_prob,
                    "trigger": f"Breakdown and decisive close below {s1}",
                    "confirmation": "Increase in red volume candles and breach of VWAP",
                    "potential_movement": f"{s1} → {s2}",
                    "expected_range": f"{s2} - {cmp:.1f}",
                    "invalidation": f"Reclaim and sustain above {r1}",
                    "time_horizon": "15-60 Minutes",
                    "risk_level": "High"
                },
                {
                    "type": "sideways",
                    "probability": side_prob,
                    "trigger": f"Price oscillates strictly within {s1} and {r1}",
                    "confirmation": "Contracting candlestick bodies and diminishing volume",
                    "potential_movement": f"Range-bound rotation within [{s1}, {r1}]",
                    "expected_range": f"{s1} - {r1}",
                    "invalidation": f"Decisive break of either {s1} or {r1}",
                    "time_horizon": "30-120 Minutes",
                    "risk_level": "Low"
                }
            ],
            "multi_timeframe_synthesis": {
                "daily_trend": "Bullish structure with higher base",
                "hourly_trend": "Bullish trend channel intact",
                "fifteen_min_structure": "Consolidation near upper pivot",
                "five_min_structure": "Breakout attempt with narrowing range",
                "overall_bias": "Bullish",
                "short_term": f"Neutral to Bullish above {cmp:.1f}",
                "medium_term": f"Bullish with trailing floor at {s2}",
                "long_term": "Positive upward trajectory"
            },
            "time_movements": [
                {
                    "timeframe": "Next 5-15 Minutes",
                    "bias": "Bullish",
                    "confidence": 76,
                    "condition": f"Price sustains above {cmp:.1f}",
                    "expected_behavior": f"Initial retest and push towards immediate resistance {r1}",
                    "invalidation": f"Slipping below intraday base {cmp - step * 0.4:.1f}"
                },
                {
                    "timeframe": "Next 15-30 Minutes",
                    "bias": "Bullish",
                    "confidence": 72,
                    "condition": f"Volume confirms breakout above {r1}",
                    "expected_behavior": f"Momentum continuation targeting {r1 + step * 0.5:.1f}",
                    "invalidation": f"Rejection pin-bar closing below {r1}"
                },
                {
                    "timeframe": "Next 30-60 Minutes",
                    "bias": "Continuation / Expansion",
                    "confidence": 68,
                    "condition": "Follow-through buyers maintain higher lows",
                    "expected_behavior": f"Approaching secondary resistance zone {r2}",
                    "invalidation": f"Sharp reversal below {s1}"
                },
                {
                    "timeframe": "Next 1-2 Hours",
                    "bias": "Trend Continuation",
                    "confidence": 62,
                    "condition": "Consolidation base holds during mid-session",
                    "expected_behavior": f"Testing upper target band {r2} - {r3}",
                    "invalidation": f"Breakdown of session VWAP support"
                }
            ],
            "trade_setup": {
                "has_setup": True,
                "direction": setup_direction,
                "entry_zone": entry_zone,
                "stop_loss": stop_loss,
                "target_1": target_1,
                "target_2": target_2,
                "risk_reward": "1 : 2.4",
                "reason": "Higher-low structure defended with expanding volume and favorable PCR support."
            },
            "risk_analysis": {
                "risk_level": "MEDIUM",
                "setup_quality": "A",
                "reward_risk": "1 : 2.4",
                "invalidation": f"Breach of critical support at {s1}",
                "main_risk": "False breakout trap near major call-writing strikes",
                "disclaimer": "This analysis is probabilistic and educational. It is not financial advice. Market conditions can change rapidly. Always independently verify levels and manage risk."
            },
            "entry_zone": entry_zone,
            "stop_loss_zone": stop_loss,
            "target_zone": f"{target_1} - {target_2}",
            "confirmation_conditions": [
                f"Sustained 5-minute candle close above {cmp:.1f}",
                "Session VWAP continues trending upward",
                "Call unwinding observed at nearest ATM strikes"
            ],
            "invalidating_conditions": [
                f"Decisive 15-minute close below stop loss ({stop_loss})",
                "Sudden spike in India VIX signaling market nervousness",
                "Aggressive Call addition at immediate resistance strikes"
            ],
            "time_horizon": "15-60 Minutes",
            "detected_overlays": [
                {"id": "r2", "type": "resistance", "label": f"R2 ({r2})", "price": r2, "y_percent": 18.0},
                {"id": "r1", "type": "resistance", "label": f"R1 ({r1})", "price": r1, "y_percent": 32.0},
                {"id": "cmp", "type": "current_price", "label": f"CMP ({cmp:.1f})", "price": cmp, "y_percent": 50.0},
                {"id": "s1", "type": "support", "label": f"S1 ({s1})", "price": s1, "y_percent": 68.0},
                {"id": "s2", "type": "support", "label": f"S2 ({s2})", "price": s2, "y_percent": 84.0}
            ],
            "ai_summary": f"Technical structure for {symbol} indicates a {bias_summary} Multi-timeframe alignment across {', '.join(timeframes) if timeframes else 'selected intervals'} presents a constructive bias towards {target_1}, provided {stop_loss} holds as invalidation threshold."
        }
