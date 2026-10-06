import os
import hashlib
from typing import List, Dict, Any, Optional
from PIL import Image
from app.services.ai.base import AIVisionProvider

class MockProvider(AIVisionProvider):
    """
    Simulated Technical Analysis Vision Provider.
    Extracts image properties (dimensions, color distribution, image hash)
    and adapts scenarios dynamically based on multi-timeframe inputs and chart differences.
    """
    async def analyze_chart(
        self,
        image_paths: List[str],
        timeframes: List[str],
        symbol: str,
        market_info: Dict[str, Any],
        notes: Optional[str] = None
    ) -> Dict[str, Any]:
        # 1. Analyze uploaded images
        total_pixels = 0
        aspect_ratio_sum = 0.0
        hash_digest = 0
        green_bias_count = 0
        red_bias_count = 0

        for path in image_paths:
            if os.path.exists(path):
                try:
                    with open(path, "rb") as f:
                        data = f.read()
                        hash_digest += int(hashlib.md5(data).hexdigest()[:8], 16)
                    with Image.open(path) as img:
                        w, h = img.size
                        total_pixels += w * h
                        aspect_ratio_sum += w / max(1, h)
                        # Sample thumbnail for dominant color evaluation
                        thumb = img.convert("RGB").resize((50, 50))
                        colors = thumb.getdata()
                        for r, g, b in colors:
                            if g > 120 and g > r + 25 and g > b + 25:
                                green_bias_count += 1
                            elif r > 120 and r > g + 25 and r > b + 25:
                                red_bias_count += 1
                except Exception:
                    pass

        # 2. Timeframe sensitivity
        tf_set = {t.lower() for t in timeframes}
        has_1hr = any("1 hour" in t or "1h" in t or "1 hr" in t or "60" in t for t in tf_set)
        has_daily = any("daily" in t or "day" in t or "1d" in t for t in tf_set)
        has_5m = any("5" in t for t in tf_set)
        has_15m = any("15" in t for t in tf_set)
        tf_count = len(timeframes)

        # 3. Base price calculation
        cmp = market_info.get("current_price")
        if not cmp:
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
                cmp = 25050.0

        # Adjust anchor price slightly based on image hash so different charts have distinct levels
        seed_offset = (hash_digest % 21) - 10 if hash_digest > 0 else 0
        step = 50.0 if cmp > 10000 else 10.0
        adjusted_cmp = round((cmp + seed_offset * (step * 0.2)) / 5) * 5

        # If 1-hour or daily is included, support/resistance bands expand
        multiplier = 1.6 if (has_1hr or has_daily) else 1.0

        r1 = round((adjusted_cmp + step * 1.5 * multiplier) / 10) * 10
        r2 = round((adjusted_cmp + step * 3.2 * multiplier) / 10) * 10
        r3 = round((adjusted_cmp + step * 5.0 * multiplier) / 10) * 10
        s1 = round((adjusted_cmp - step * 1.5 * multiplier) / 10) * 10
        s2 = round((adjusted_cmp - step * 3.0 * multiplier) / 10) * 10
        s3 = round((adjusted_cmp - step * 4.8 * multiplier) / 10) * 10

        # 4. Determine bias from image colors, notes, and multi-TF composition
        notes_lower = (notes or "").lower()
        is_bull_note = "support" in notes_lower or "gap-up" in notes_lower or "call" in notes_lower or "long" in notes_lower
        is_bear_note = "resistance" in notes_lower or "breakdown" in notes_lower or "put" in notes_lower or "short" in notes_lower

        # Dynamic bias based on visual image clusters
        color_diff = green_bias_count - red_bias_count
        hash_variant = (hash_digest % 7)

        if is_bear_note:
            primary = "bearish"
            bull_prob = 20
            bear_prob = 70
            side_prob = 10
        elif is_bull_note:
            primary = "bullish"
            bull_prob = 72
            bear_prob = 18
            side_prob = 10
        elif color_diff < -50 or hash_variant in [0, 1]:
            primary = "bearish"
            bull_prob = 24
            bear_prob = 64
            side_prob = 12
        elif abs(color_diff) < 20 or hash_variant in [2]:
            primary = "sideways"
            bull_prob = 32
            bear_prob = 30
            side_prob = 38
        else:
            primary = "bullish"
            bull_prob = 66
            bear_prob = 22
            side_prob = 12

        # 5. Multi-timeframe confidence boost
        # More timeframe charts uploaded (e.g. 5m + 15m + 1h) = higher confidence
        base_confidence = 68
        if tf_count >= 3:
            confidence = min(88, base_confidence + 12 + (hash_digest % 5))
        elif tf_count == 2:
            confidence = min(82, base_confidence + 6 + (hash_digest % 5))
        else:
            confidence = base_confidence + (hash_digest % 5)

        # 6. Trend & Structure
        if primary == "bullish":
            trend = "Bullish"
            structure = "Higher High + Higher Low"
            setup_dir = "CALL"
            entry_zone = f"{adjusted_cmp - step * 0.2:.1f} - {adjusted_cmp + step * 0.4:.1f}"
            stop_loss = f"{s1}"
            target_1 = f"{r1}"
            target_2 = f"{r2}"
            bias_summary = f"Upward trend continuation structure with higher base support around {s1}."
        elif primary == "bearish":
            trend = "Bearish"
            structure = "Lower High + Lower Low"
            setup_dir = "PUT"
            entry_zone = f"{adjusted_cmp - step * 0.4:.1f} - {adjusted_cmp + step * 0.2:.1f}"
            stop_loss = f"{r1}"
            target_1 = f"{s1}"
            target_2 = f"{s2}"
            bias_summary = f"Supply pressure and rejection below key overhead resistance at {r1}."
        else:
            trend = "Neutral / Sideways"
            structure = "Range-bound Consolidation"
            setup_dir = "NO TRADE"
            entry_zone = f"{s1} - {r1}"
            stop_loss = f"{s2}"
            target_1 = f"{r1}"
            target_2 = f"{s1}"
            bias_summary = f"Contracting volatility between key support {s1} and resistance {r1}."

        pcr = market_info.get("pcr") or 1.15
        vix = market_info.get("india_vix") or 13.8

        # Hourly trend synthesis
        hourly_summary = "Bullish momentum channel" if has_1hr and primary == "bullish" else (
            "Distribution below hourly 50 EMA" if has_1hr and primary == "bearish" else (
                "Horizontal channel oscillation" if has_1hr else "Not uploaded (inferred from intraday)"
            )
        )

        return {
            "trend": trend,
            "primary_scenario": primary,
            "confidence_score": confidence,
            "market_structure": {
                "trend": trend,
                "structure": structure,
                "momentum": "Strong" if confidence >= 78 else "Moderate",
                "volatility": f"Normal (VIX ~ {vix})",
                "liquidity": "High across benchmark strikes"
            },
            "support_levels": [
                {"label": "Support 1 (S1)", "price": s1, "strength": "Strong", "description": "Immediate swing support & pivot floor"},
                {"label": "Support 2 (S2)", "price": s2, "strength": "Major", "description": "Prior day value area low"},
                {"label": "Support 3 (S3)", "price": s3, "strength": "Weekly", "description": "Macro demand pocket"}
            ],
            "resistance_levels": [
                {"label": "Resistance 1 (R1)", "price": r1, "strength": "Strong", "description": "Overhead swing high & Call OI cluster"},
                {"label": "Resistance 2 (R2)", "price": r2, "strength": "Key", "description": "Breakout expansion hurdle"},
                {"label": "Resistance 3 (R3)", "price": r3, "strength": "Major", "description": "Fibonacci extension"}
            ],
            "candlestick_analysis": {
                "patterns_detected": [
                    "Hammer rejection at support" if primary == "bullish" else "Shooting Star rejection at resistance",
                    f"{'Multi-timeframe 1H + 15M candle alignment' if has_1hr else 'Intraday consolidation bar cluster'}"
                ],
                "observation": f"Chart exhibits {structure.lower()} across uploaded timeframes ({', '.join(timeframes)})."
            },
            "volume_analysis": {
                "trend": "Expanding on momentum waves",
                "observation": f"Volume activity confirms {trend.lower()} bias on primary timeframe."
            },
            "oi_analysis": {
                "pcr_reading": str(pcr),
                "observation": f"PCR reading of {pcr} aligns with current technical support level at {s1}."
            },
            "technical_indicators": {
                "moving_averages": f"Price trading {'above' if primary == 'bullish' else 'below'} 20 EMA and 50 SMA",
                "rsi": f"{'62.4 - Bullish momentum' if primary == 'bullish' else ('38.2 - Bearish momentum' if primary == 'bearish' else '50.1 - Neutral range')}",
                "vwap": f"Holding {'above' if primary == 'bullish' else 'below'} Session VWAP"
            },
            "scenarios": [
                {
                    "type": "bullish",
                    "probability": bull_prob,
                    "trigger": f"Sustained 5M candle close above {adjusted_cmp + step * 0.4:.1f}",
                    "confirmation": "Volume expansion on green candles and RSI sustaining above 55",
                    "potential_movement": f"{adjusted_cmp:.1f} → {r1} (Target 1), then {r2} (Target 2)",
                    "expected_range": f"{s1} - {r2}",
                    "invalidation": f"15M candle close below key support {s1}",
                    "time_horizon": "1-2 Hours" if has_1hr else "15-60 Minutes",
                    "risk_level": "Medium"
                },
                {
                    "type": "bearish",
                    "probability": bear_prob,
                    "trigger": f"Breakdown and decisive close below {s1}",
                    "confirmation": "Increase in red volume candles and breach of VWAP",
                    "potential_movement": f"{s1} → {s2}",
                    "expected_range": f"{s2} - {adjusted_cmp:.1f}",
                    "invalidation": f"Reclaim and sustain above {r1}",
                    "time_horizon": "1-2 Hours" if has_1hr else "15-60 Minutes",
                    "risk_level": "High"
                },
                {
                    "type": "sideways",
                    "probability": side_prob,
                    "trigger": f"Price oscillates strictly within [{s1}, {r1}]",
                    "confirmation": "Contracting candlestick bodies and low directional momentum",
                    "potential_movement": f"Range-bound rotation within [{s1}, {r1}]",
                    "expected_range": f"{s1} - {r1}",
                    "invalidation": f"Decisive break of either {s1} or {r1}",
                    "time_horizon": "30-120 Minutes",
                    "risk_level": "Low"
                }
            ],
            "multi_timeframe_synthesis": {
                "daily_trend": "Higher timeframe structure intact",
                "hourly_trend": hourly_summary,
                "fifteen_min_structure": f"15M structure showing {trend.lower()} characteristics",
                "five_min_structure": "5M tactical execution setup",
                "overall_bias": trend,
                "short_term": f"{'Bullish' if primary == 'bullish' else 'Bearish'} above {adjusted_cmp:.1f}",
                "medium_term": f"{trend} with trailing pivot at {s1 if primary == 'bullish' else r1}",
                "long_term": "Constructive macro channel"
            },
            "time_movements": [
                {
                    "timeframe": "Next 5-15 Minutes",
                    "bias": trend,
                    "confidence": confidence,
                    "condition": f"Price sustains {'above' if primary == 'bullish' else 'below'} {adjusted_cmp:.1f}",
                    "expected_behavior": f"Initial push towards immediate pivot {r1 if primary == 'bullish' else s1}",
                    "invalidation": f"Breach of local level {s1 if primary == 'bullish' else r1}"
                },
                {
                    "timeframe": "Next 15-30 Minutes",
                    "bias": trend,
                    "confidence": max(50, confidence - 4),
                    "condition": f"Volume confirms follow-through on {timeframes[0] if timeframes else '15m'}",
                    "expected_behavior": f"Test of overhead hurdle {r1 if primary == 'bullish' else s1}",
                    "invalidation": "Sharp reversal bar closing beyond median"
                },
                {
                    "timeframe": "Next 30-60 Minutes",
                    "bias": f"{trend} Continuation",
                    "confidence": max(50, confidence - 8),
                    "condition": "Follow-through buyers maintain structural pivot",
                    "expected_behavior": f"Approaching target zone {r2 if primary == 'bullish' else s2}",
                    "invalidation": f"False breakout trap returning into range"
                },
                {
                    "timeframe": "Next 1-2 Hours",
                    "bias": "Multi-Timeframe Trend Continuation" if has_1hr else "Consolidation Base",
                    "confidence": max(50, confidence - 12),
                    "condition": f"{'1-Hour chart higher base holds' if has_1hr else 'Intraday consolidation base holds'}",
                    "expected_behavior": f"Testing extended target band {r2} - {r3}",
                    "invalidation": "Loss of primary support"
                }
            ],
            "trade_setup": {
                "has_setup": primary != "sideways",
                "direction": setup_dir,
                "entry_zone": entry_zone,
                "stop_loss": stop_loss,
                "target_1": target_1,
                "target_2": target_2,
                "risk_reward": "1 : 2.4" if primary != "sideways" else "N/A",
                "reason": (
                    f"Confluence across {tf_count} timeframe(s) ({', '.join(timeframes)}) supporting {primary} bias."
                    if primary != "sideways"
                    else "Market is range-bound without clear directional confirmation. Recommending NO TRADE."
                )
            },
            "risk_analysis": {
                "risk_level": "LOW" if confidence >= 80 else ("MEDIUM" if confidence >= 65 else "HIGH"),
                "setup_quality": "A" if confidence >= 80 else ("B" if confidence >= 68 else "C"),
                "reward_risk": "1 : 2.4" if primary != "sideways" else "N/A",
                "invalidation": f"Breach of critical pivot at {stop_loss}",
                "main_risk": "False breakout trap near major strike cluster",
                "disclaimer": "This analysis is probabilistic and educational. It is not financial advice. Market conditions can change rapidly. Always independently verify levels and manage risk."
            },
            "entry_zone": entry_zone,
            "stop_loss_zone": stop_loss,
            "target_zone": f"{target_1} - {target_2}",
            "confirmation_conditions": [
                f"Sustained 5-minute candle close above {adjusted_cmp:.1f}",
                f"{'1-Hour trend direction confirmation' if has_1hr else 'Session VWAP upward trend'}",
                "Call/Put open interest unwinding at nearest strike"
            ],
            "invalidating_conditions": [
                f"Decisive 15-minute close below stop loss ({stop_loss})",
                "Sudden spike in India VIX signaling market volatility shift",
                "Aggressive contrary OI addition at immediate strike"
            ],
            "time_horizon": "1-2 Hours" if has_1hr else "15-60 Minutes",
            "detected_overlays": [
                {"id": "r2", "type": "resistance", "label": f"R2 ({r2})", "price": r2, "y_percent": 18.0},
                {"id": "r1", "type": "resistance", "label": f"R1 ({r1})", "price": r1, "y_percent": 32.0},
                {"id": "cmp", "type": "current_price", "label": f"CMP ({adjusted_cmp:.1f})", "price": adjusted_cmp, "y_percent": 50.0},
                {"id": "s1", "type": "support", "label": f"S1 ({s1})", "price": s1, "y_percent": 68.0},
                {"id": "s2", "type": "support", "label": f"S2 ({s2})", "price": s2, "y_percent": 84.0}
            ],
            "ai_summary": f"Technical analysis for {symbol} across {tf_count} timeframe(s) ({', '.join(timeframes)}): {bias_summary} {'Adding 1-Hour chart confirms higher timeframe trend structure.' if has_1hr else ''} Target 1 is at {target_1} with strict invalidation at {stop_loss}."
        }
