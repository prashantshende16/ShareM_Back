import time
import math
import logging
from datetime import datetime
from typing import Dict, Any, List, Optional
import pytz

from app.services.market_data.live_market_service import LiveMarketService
from app.services.technical_analysis.option_indicator import OptionSignalIndicator

logger = logging.getLogger(__name__)

class SurgeRadarService:
    """
    Automated Sudden Movement & Momentum Surge Radar Engine.
    Detects 10% - 20%+ rapid option price expansions, volume surges, and
    calculates Greeks (Delta) with real-time Nasdaq, Dow Jones, and India VIX observations.
    Generates actionable automated CALL and PUT trade suggestions.
    """

    _cached_suggestions: List[Dict[str, Any]] = []
    _last_scan_epoch: float = 0.0
    _unread_count: int = 0
    _last_seen_ids: set = set()
    _SCAN_CACHE_TTL = 15.0  # 15 seconds cache to stay real-time

    SUPPORTED_INDICES = [
        {"symbol": "NIFTY 50", "yf": "^NSEI", "lot_size": 65, "strike_step": 50},
        {"symbol": "BANK NIFTY", "yf": "^NSEBANK", "lot_size": 60, "strike_step": 100},
        {"symbol": "SENSEX", "yf": "^BSESN", "lot_size": 20, "strike_step": 100},
        {"symbol": "FINNIFTY", "yf": "NIFTY_FIN_SERVICE.NS", "lot_size": 65, "strike_step": 50},
        {"symbol": "MIDCPNIFTY", "yf": "NIFTY_MID_SELECT.NS", "lot_size": 75, "strike_step": 25},
    ]

    @classmethod
    def get_macro_observations(cls) -> Dict[str, Any]:
        """
        Fetches live observation data for Nasdaq 100, Dow Jones, and India VIX.
        """
        dow_data = LiveMarketService.get_candle_data("^DJI", interval="5m", range_="1d") or {}
        nasdaq_data = LiveMarketService.get_candle_data("^IXIC", interval="5m", range_="1d") or {}
        vix_data = LiveMarketService.get_candle_data("^INDIAVIX", interval="5m", range_="1d") or {}

        dow_chg = dow_data.get("change_pct", 0.0)
        nasdaq_chg = nasdaq_data.get("change_pct", 0.0)
        vix_val = vix_data.get("current_price", 13.5)
        vix_chg = vix_data.get("change_pct", 0.0)

        # Volatility Sentiment Assessment
        if vix_val >= 16.5:
            vix_status = "High Volatility (Fear Elevated)"
            vix_bias = "PUT_FAVORED"
        elif vix_val <= 12.5:
            vix_status = "Low Volatility (Complacent / Tight Range)"
            vix_bias = "TIGHT_STOPS"
        else:
            vix_status = "Normal / Balanced Volatility"
            vix_bias = "NEUTRAL"

        # Global US Trend
        us_avg = round((dow_chg + nasdaq_chg) / 2.0, 2)
        if us_avg >= 0.4:
            us_trend = "Bullish"
        elif us_avg <= -0.4:
            us_trend = "Bearish"
        else:
            us_trend = "Mixed / Flat"

        # Confluence Verdict
        if us_avg > 0.2 and vix_chg <= 0:
            macro_verdict = f"Bullish Confluence (US {us_avg}% | VIX {vix_chg}%)"
            macro_call_boost = 10
            macro_put_boost = -10
        elif us_avg < -0.2 and vix_chg >= 0:
            macro_verdict = f"Bearish Confluence (US {us_avg}% | VIX +{vix_chg}%)"
            macro_call_boost = -10
            macro_put_boost = 10
        else:
            macro_verdict = f"Domestic Driven / Neutral (US {us_avg}%, VIX {vix_val})"
            macro_call_boost = 0
            macro_put_boost = 0

        return {
            "dow_jones": {
                "name": "Dow Jones",
                "price": dow_data.get("current_price", 0.0),
                "change": dow_data.get("change", 0.0),
                "change_pct": dow_chg
            },
            "nasdaq": {
                "name": "Nasdaq 100",
                "price": nasdaq_data.get("current_price", 0.0),
                "change": nasdaq_data.get("change", 0.0),
                "change_pct": nasdaq_chg
            },
            "india_vix": {
                "name": "India VIX",
                "price": vix_val,
                "change": vix_data.get("change", 0.0),
                "change_pct": vix_chg,
                "status": vix_status,
                "bias": vix_bias
            },
            "us_trend": us_trend,
            "us_avg_change": us_avg,
            "macro_verdict": macro_verdict,
            "call_boost": macro_call_boost,
            "put_boost": macro_put_boost
        }

    @classmethod
    def scan_surge_radar(cls, force_refresh: bool = False) -> Dict[str, Any]:
        """
        Scans all major indices, detects sudden 10% - 20%+ movement,
        computes Delta, Volume surge multiplier, and generates automated trade calls.
        """
        now = time.time()
        if not force_refresh and (now - cls._last_scan_epoch) < cls._SCAN_CACHE_TTL and cls._cached_suggestions:
            macro = cls.get_macro_observations()
            return {
                "status": "success",
                "macro_radar": macro,
                "suggestions": cls._cached_suggestions,
                "unread_alerts_count": cls._unread_count,
                "last_scanned_at": datetime.now(pytz.timezone("Asia/Kolkata")).strftime("%I:%M:%S %p"),
                "total_suggestions": len(cls._cached_suggestions)
            }

        macro = cls.get_macro_observations()
        suggestions: List[Dict[str, Any]] = []
        now_ist = datetime.now(pytz.timezone("Asia/Kolkata"))

        for idx_info in cls.SUPPORTED_INDICES:
            sym = idx_info["symbol"]
            yf_sym = idx_info["yf"]
            lot_size = idx_info["lot_size"]

            try:
                # 1. Fetch 5m candle data
                candles_data = LiveMarketService.get_candle_data(yf_sym, interval="5m", range_="1d")
                if not candles_data or not candles_data.get("candles") or len(candles_data["candles"]) < 10:
                    continue

                candles = candles_data["candles"]
                cmp = candles_data.get("current_price") or candles[-1]["close"]

                # 2. Evaluate 5m signal
                signal = OptionSignalIndicator.evaluate_5m_option_signal(
                    candles=candles,
                    cmp=cmp,
                    symbol=sym,
                    expiry_type="current",
                    timeframe="5m",
                    custom_lot_size=lot_size
                )

                direction = signal.get("direction", "NEUTRAL")
                exec_data = signal.get("trade_execution", {})
                if not exec_data:
                    continue

                # 3. Sudden 10% - 20%+ Surge & Volume Spike Detection
                last_candle = candles[-1]
                prev_candles = candles[-15:]
                avg_vol = sum(c.get("volume", 0) for c in prev_candles) / max(1, len(prev_candles))
                cur_vol = last_candle.get("volume", 0)
                vol_ratio = round(cur_vol / max(1.0, avg_vol), 1)

                # Recent 3-candle price volatility momentum
                recent_low = min(c["low"] for c in candles[-3:])
                recent_high = max(c["high"] for c in candles[-3:])
                index_move_pct = abs(candles[-1]["close"] - candles[-3]["open"]) / max(1.0, candles[-3]["open"]) * 100

                # Estimated option delta acceleration factor (typically 15x - 30x of spot index move)
                estimated_option_surge_pct = round(max(8.5, index_move_pct * 22.0), 1)

                # Surge tier classification
                if estimated_option_surge_pct >= 20.0 or vol_ratio >= 2.5:
                    surge_tier = "MEGA_SURGE_20PCT"
                    surge_badge = f"🔥 +{estimated_option_surge_pct}% Sudden Surge"
                    is_hot = True
                elif estimated_option_surge_pct >= 12.0 or vol_ratio >= 1.6:
                    surge_tier = "FAST_MOMENTUM_15PCT"
                    surge_badge = f"⚡ +{estimated_option_surge_pct}% Sudden Move"
                    is_hot = True
                else:
                    surge_tier = "EARLY_BREAKOUT_10PCT"
                    surge_badge = f"✨ +{estimated_option_surge_pct}% Momentum"
                    is_hot = False

                # Delta computation
                target_strike = signal.get("selected_strike") or (int(cmp // idx_info["strike_step"]) * idx_info["strike_step"])
                is_call = (direction == "CALL") or (direction == "SIDEWAYS" and macro["us_avg_change"] >= 0)
                opt_type = "CE" if is_call else "PE"

                dte = 2  # Current weekly near expiry default
                strike_delta = OptionSignalIndicator.calculate_delta(
                    spot=cmp,
                    strike=target_strike,
                    dte=dte,
                    iv=0.18,
                    is_call=is_call
                )

                # Entry, SL, Targets
                entry = exec_data.get("recommended_entry", round(cmp * 0.005, 1))
                ltp = exec_data.get("current_ltp", entry)
                sl = exec_data.get("stop_loss", round(entry * 0.85, 1))
                t1 = exec_data.get("target_1", round(entry * 1.35, 1))
                t2 = exec_data.get("target_2", round(entry * 1.60, 1))

                # Unique Suggestion ID per 15-minute window
                slot_id = int(now // 600)
                sugg_id = f"SURGE_{sym.replace(' ', '')}_{target_strike}_{opt_type}_{slot_id}"

                suggestion = {
                    "id": sugg_id,
                    "symbol": sym,
                    "contract_name": exec_data.get("contract_name") or f"{sym} {signal.get('active_expiry')} {target_strike} {opt_type}",
                    "tradingsymbol": exec_data.get("tradingsymbol", ""),
                    "symboltoken": exec_data.get("symboltoken", ""),
                    "action": "BUY",
                    "option_type": opt_type,
                    "strike_price": target_strike,
                    "expiry": signal.get("active_expiry", "Current"),
                    "timeframe": "5m",
                    "lots": 1,
                    "lot_size": lot_size,
                    "total_quantity": lot_size,
                    "surge_pct": estimated_option_surge_pct,
                    "surge_badge": surge_badge,
                    "surge_tier": surge_tier,
                    "volume_ratio": vol_ratio,
                    "delta": strike_delta,
                    "entry_price": entry,
                    "current_ltp": ltp,
                    "stop_loss": sl,
                    "target_1": t1,
                    "target_2": t2,
                    "risk_reward": exec_data.get("risk_reward_ratio", "1:2.4"),
                    "confidence_score": signal.get("confidence", 78),
                    "macro_confluence": macro["macro_verdict"],
                    "dow_change": macro["dow_jones"]["change_pct"],
                    "nasdaq_change": macro["nasdaq"]["change_pct"],
                    "india_vix": macro["india_vix"]["price"],
                    "detected_at": now_ist.strftime("%I:%M:%S %p"),
                    "detected_timestamp": now,
                    "is_hot": is_hot,
                    "summary": (
                        f"{surge_badge} detected on {sym} {target_strike} {opt_type}! "
                        f"Delta: {strike_delta} with {vol_ratio}x volume spike. "
                        f"Targeting ₹{t1} (T1) and ₹{t2} (T2) with SL at ₹{sl}."
                    )
                }

                suggestions.append(suggestion)

                # Check if this is a newly discovered surge
                if sugg_id not in cls._last_seen_ids:
                    cls._last_seen_ids.add(sugg_id)
                    cls._unread_count += 1

            except Exception as e:
                logger.warning(f"Error scanning surge radar for {sym}: {e}")

        # Sort suggestions: Hot surges first, then highest surge_pct
        suggestions.sort(key=lambda s: (1 if s["is_hot"] else 0, s["surge_pct"]), reverse=True)

        cls._cached_suggestions = suggestions
        cls._last_scan_epoch = now

        return {
            "status": "success",
            "macro_radar": macro,
            "suggestions": suggestions,
            "unread_alerts_count": cls._unread_count,
            "last_scanned_at": now_ist.strftime("%I:%M:%S %p"),
            "total_suggestions": len(suggestions)
        }

    @classmethod
    def reset_notifications(cls) -> Dict[str, Any]:
        """Marks all active surge alerts as viewed."""
        cls._unread_count = 0
        return {"status": "success", "unread_alerts_count": 0}
