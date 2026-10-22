import json
import logging
from typing import Dict, Any, Optional, List
from datetime import datetime
import pytz

from app.config import settings
from app.services.market_data.live_market_service import LiveMarketService
from app.services.technical_analysis.option_indicator import OptionSignalIndicator
from app.services.market_data.angel_one_service import AngelOneService
from app.services.ai.gemini_provider import GeminiProvider

logger = logging.getLogger(__name__)

class AIMarketStrategyAgent:
    """
    AI Live Market Strategy Agent.
    Blends:
    1. Angel One SmartAPI live option contracts & LTPs
    2. Multi-timeframe technical indicator matrix (5-Min Scalp + 15-Min Trend)
    3. Global Market Radar (US Dow/S&P/Nasdaq, UK FTSE, DAX, Crude Oil, USD/INR)
    4. Real-time news tally at current market timing
    5. Google Gemini Generative AI synthesis
    """

    @classmethod
    async def synthesize_market_strategy(
        cls,
        symbol: str = "NIFTY 50",
        expiry_type: str = "current",
        timeframe: str = "5m"
    ) -> Dict[str, Any]:
        ist = pytz.timezone("Asia/Kolkata")
        now_ist = datetime.now(ist)
        clean_sym = symbol.strip().upper()
        yf_sym = LiveMarketService.resolve_symbol(clean_sym)

        # 1. Fetch 5-minute technical candle data & signal
        data_5m = LiveMarketService.get_candle_data(yf_sym, interval="5m", range_="5d")
        if not data_5m or not data_5m.get("candles"):
            data_5m = LiveMarketService.get_candle_data(yf_sym, interval="5m", range_="1d")
        candles_5m = data_5m.get("candles", []) if data_5m else []
        cmp = data_5m.get("current_price", 0.0) if data_5m else 0.0

        signal_5m = OptionSignalIndicator.evaluate_5m_option_signal(
            candles_5m, cmp, symbol=clean_sym, expiry_type=expiry_type, timeframe="5m"
        )

        # 2. Fetch 15-minute technical candle data & signal
        data_15m = LiveMarketService.get_candle_data(yf_sym, interval="15m", range_="5d")
        candles_15m = data_15m.get("candles", []) if data_15m else []
        signal_15m = OptionSignalIndicator.evaluate_5m_option_signal(
            candles_15m, cmp, symbol=clean_sym, expiry_type=expiry_type, timeframe="15m"
        )

        # Active chosen signal based on user's requested timeframe
        is_user_15m = timeframe.lower() in ["15m", "15", "15min"]
        active_signal = signal_15m if is_user_15m else signal_5m

        # 3. Global Market Radar (US, UK/Europe, Asia, Crude, USD/INR, News Tally)
        global_radar = LiveMarketService.get_global_market_radar()

        # 4. Angel One Live Option Quote verification
        trade_exec = active_signal.get("trade_execution", {})
        angel_ltp = trade_exec.get("current_ltp", 0.0)
        contract_name = trade_exec.get("contract_name", f"{clean_sym} {active_signal.get('strike_suggestion')}")

        # 5. Dual Timeframe Harmony Assessment
        dir_5m = signal_5m.get("direction", "NEUTRAL")
        dir_15m = signal_15m.get("direction", "NEUTRAL")
        conf_5m = signal_5m.get("confidence", 50)
        conf_15m = signal_15m.get("confidence", 50)

        if dir_5m == dir_15m and dir_5m in ["CALL", "PUT"]:
            alignment = f"Full Alignment ({dir_5m} Momentum on both 5m and 15m)"
            alignment_status = "ALIGNED_HIGH_CONVICTION"
        elif dir_15m in ["CALL", "PUT"] and dir_5m == "NEUTRAL":
            alignment = f"15m Trend Dominant ({dir_15m}) with 5m Consolidation"
            alignment_status = "TREND_CONTINUATION"
        elif dir_5m != dir_15m and dir_5m != "NEUTRAL" and dir_15m != "NEUTRAL":
            alignment = f"Counter-Trend Pullback (5m {dir_5m} vs 15m {dir_15m})"
            alignment_status = "COUNTER_TREND_WARNING"
        else:
            alignment = "Range-Bound Consolidation across 5m and 15m"
            alignment_status = "RANGE_BOUND"

        # 6. Attempt Gemini Generative AI Synthesis
        ai_result = None
        gemini_key = settings.GEMINI_API_KEY
        if gemini_key:
            try:
                ai_result = await cls._invoke_gemini_synthesis(
                    symbol=clean_sym,
                    cmp=cmp,
                    signal_5m=signal_5m,
                    signal_15m=signal_15m,
                    global_radar=global_radar,
                    trade_exec=trade_exec,
                    alignment=alignment,
                    now_str=now_ist.strftime("%d %b %Y, %I:%M:%S %p IST")
                )
            except Exception as e:
                logger.warning(f"Gemini API invocation fallback to rules-based synthesizer: {e}")

        # 7. Fallback to deterministic institutional rule synthesis if Gemini is offline
        if not ai_result:
            ai_result = cls._build_rule_based_synthesis(
                symbol=clean_sym,
                cmp=cmp,
                signal_5m=signal_5m,
                signal_15m=signal_15m,
                global_radar=global_radar,
                trade_exec=trade_exec,
                alignment=alignment,
                alignment_status=alignment_status,
                active_signal=active_signal,
                timeframe=timeframe
            )

        return {
            "status": "success",
            "symbol": clean_sym,
            "evaluated_at": now_ist.strftime("%I:%M:%S %p IST"),
            "timestamp_iso": now_ist.isoformat(),
            "timeframe": "15 Minute" if is_user_15m else "5 Minute",
            "active_signal": active_signal,
            "signal_5m_summary": {
                "decision": signal_5m.get("decision"),
                "direction": signal_5m.get("direction"),
                "confidence": conf_5m,
                "strike": signal_5m.get("strike_suggestion"),
                "confluence_percentage": signal_5m.get("confluence_score", {}).get("percentage", 0)
            },
            "signal_15m_summary": {
                "decision": signal_15m.get("decision"),
                "direction": signal_15m.get("direction"),
                "confidence": conf_15m,
                "strike": signal_15m.get("strike_suggestion"),
                "confluence_percentage": signal_15m.get("confluence_score", {}).get("percentage", 0)
            },
            "timeframe_alignment": {
                "label": alignment,
                "status": alignment_status,
                "is_confluent": dir_5m == dir_15m and dir_5m in ["CALL", "PUT"]
            },
            "global_radar": global_radar,
            "agent_strategy": ai_result
        }

    @classmethod
    async def _invoke_gemini_synthesis(
        cls,
        symbol: str,
        cmp: float,
        signal_5m: Dict[str, Any],
        signal_15m: Dict[str, Any],
        global_radar: Dict[str, Any],
        trade_exec: Dict[str, Any],
        alignment: str,
        now_str: str
    ) -> Optional[Dict[str, Any]]:
        prompt = f"""
You are the Chief Quantitative F&O Strategist for Indian Markets at ShareM.
Synthesize the following live market intelligence into an institutional trade strategy:

TARGET MARKET: {symbol} (Spot CMP: ₹{cmp})
EVALUATED AT: {now_str}

1. TIMEFRAME TECHNICAL DATA:
- 5-Min Decision: {signal_5m.get('decision')} (Confidence: {signal_5m.get('confidence')}%)
- 5-Min Strike: {signal_5m.get('strike_suggestion')}
- 5-Min EMA 9/21: {signal_5m.get('indicators', {}).get('trend_ribbon')}
- 5-Min VWAP: {signal_5m.get('indicators', {}).get('vwap')}
- 5-Min RSI: {signal_5m.get('indicators', {}).get('rsi_14')}
- 15-Min Decision: {signal_15m.get('decision')} (Confidence: {signal_15m.get('confidence')}%)
- 15-Min Strike: {signal_15m.get('strike_suggestion')}
- Dual Timeframe Alignment: {alignment}

2. REAL ANGEL ONE SMARTAPI QUOTE:
- Contract: {trade_exec.get('contract_name')}
- Current LTP: ₹{trade_exec.get('current_ltp')}
- Recommended Entry: ₹{trade_exec.get('recommended_entry')}
- Stop Loss: ₹{trade_exec.get('stop_loss')}
- Target 1: ₹{trade_exec.get('target_1')} | Target 2: ₹{trade_exec.get('target_2')}
- Day High: ₹{trade_exec.get('day_high')} | Day Low: ₹{trade_exec.get('day_low')}

3. GLOBAL MARKET RADAR (US, UK/Europe, Commodities):
- Global Verdict: {global_radar.get('global_verdict')} (Score: {global_radar.get('global_score')}/100)
- US Market Stance: {global_radar.get('us_market_stance')} (Avg: {global_radar.get('us_avg_change')}%)
- UK Market Stance: {global_radar.get('uk_market_stance')} (Avg: {global_radar.get('uk_avg_change')}%)
- Crude Oil Status: {global_radar.get('crude_oil_status')}

4. CURRENT NEWS TALLY HEADLINES:
{json.dumps([n.get('title') for n in global_radar.get('news_tally', [])[:4]])}

INSTRUCTIONS:
Return STRICTLY valid JSON ONLY adhering to this exact schema (no markdown, no backticks):
{{
  "verdict": "STRONG BUY CALL" | "BUY CALL ON DIP" | "STRONG BUY PUT" | "BUY PUT ON PULLBACK" | "WAIT / NO TRADE (Range-Bound)",
  "conviction": "HIGH" | "MODERATE" | "LOW",
  "confidence_score": 85,
  "macro_global_context": "2-3 sentences analyzing how US/UK markets, crude oil, and current news tally impact Indian market today.",
  "timeframe_harmony": "1-2 sentences explaining alignment between 5-min scalp and 15-min trend.",
  "technical_edge": "Key confluence points (EMA ribbon, VWAP, RSI, MACD, CPR pivots).",
  "recommended_contract": "{trade_exec.get('contract_name')}",
  "live_ltp": {trade_exec.get('current_ltp', 0.0)},
  "trigger_entry": {trade_exec.get('recommended_entry', 0.0)},
  "stop_loss": {trade_exec.get('stop_loss', 0.0)},
  "target_1": {trade_exec.get('target_1', 0.0)},
  "target_2": {trade_exec.get('target_2', 0.0)},
  "risk_reward": "{trade_exec.get('risk_reward_ratio', '1:2.0')}",
  "holding_horizon": "15 to 30 mins (Scalp) / 45 to 90 mins (Momentum)",
  "key_catalysts_and_watchouts": ["Watchout 1", "Watchout 2", "Watchout 3"]
}}
"""
        provider = GeminiProvider()
        import httpx
        async with httpx.AsyncClient(timeout=30.0) as client:
            model_name = await provider.get_working_model(client)
            url = f"https://generativelanguage.googleapis.com/v1beta/models/{model_name}:generateContent?key={provider.api_key}"
            payload = {
                "contents": [{"parts": [{"text": prompt}]}],
                "generationConfig": {
                    "response_mime_type": "application/json",
                    "temperature": 0.2
                }
            }
            resp = await client.post(url, json=payload)
            if resp.status_code == 200:
                data = resp.json()
                cand = data.get("candidates", [])
                if cand and "content" in cand[0]:
                    parts = cand[0]["content"].get("parts", [])
                    if parts and "text" in parts[0]:
                        raw = parts[0]["text"].strip()
                        if raw.startswith("```json"):
                            raw = raw[7:]
                        if raw.startswith("```"):
                            raw = raw[3:]
                        if raw.endswith("```"):
                            raw = raw[:-3]
                        return json.loads(raw.strip())
        return None

    @classmethod
    def _build_rule_based_synthesis(
        cls,
        symbol: str,
        cmp: float,
        signal_5m: Dict[str, Any],
        signal_15m: Dict[str, Any],
        global_radar: Dict[str, Any],
        trade_exec: Dict[str, Any],
        alignment: str,
        alignment_status: str,
        active_signal: Dict[str, Any],
        timeframe: str
    ) -> Dict[str, Any]:
        dir_5m = signal_5m.get("direction", "NEUTRAL")
        dir_15m = signal_15m.get("direction", "NEUTRAL")
        us_stance = global_radar.get("us_market_stance", "Mixed")
        uk_stance = global_radar.get("uk_market_stance", "Mixed")
        g_verdict = global_radar.get("global_verdict", "Neutral")

        # Determine strategy verdict
        if dir_5m == "CALL" and dir_15m == "CALL":
            verdict = "STRONG BUY CALL"
            conviction = "HIGH"
            confidence = 88
        elif dir_5m == "PUT" and dir_15m == "PUT":
            verdict = "STRONG BUY PUT"
            conviction = "HIGH"
            confidence = 88
        elif active_signal.get("direction") == "CALL":
            verdict = "BUY CALL ON DIP"
            conviction = "MODERATE"
            confidence = 74
        elif active_signal.get("direction") == "PUT":
            verdict = "BUY PUT ON PULLBACK"
            conviction = "MODERATE"
            confidence = 74
        else:
            verdict = "WAIT / NO TRADE (Range-Bound)"
            conviction = "LOW"
            confidence = 52

        macro_ctx = (
            f"Global sentiment is currently {g_verdict}. US markets are {us_stance} "
            f"(Dow/Nasdaq/S&P avg {global_radar.get('us_avg_change')}%), while UK/European markets are {uk_stance}. "
            f"Crude oil status is {global_radar.get('crude_oil_status')}, providing a baseline directional cue for Indian equities."
        )

        tech_edge = (
            f"5-Min signal is {signal_5m.get('decision')} with {signal_5m.get('confluence_score', {}).get('confirmed', 4)}/10 indicators confirmed. "
            f"15-Min trend is {signal_15m.get('decision')}. VWAP at {active_signal.get('indicators', {}).get('vwap')} "
            f"and EMA 9/21 ribbon confirm {active_signal.get('indicators', {}).get('trend_ribbon')} momentum."
        )

        return {
            "verdict": verdict,
            "conviction": conviction,
            "confidence_score": confidence,
            "macro_global_context": macro_ctx,
            "timeframe_harmony": f"Dual Timeframe: {alignment}.",
            "technical_edge": tech_edge,
            "recommended_contract": trade_exec.get("contract_name", f"{symbol} Option"),
            "live_ltp": trade_exec.get("current_ltp", 0.0),
            "trigger_entry": trade_exec.get("recommended_entry", 0.0),
            "stop_loss": trade_exec.get("stop_loss", 0.0),
            "target_1": trade_exec.get("target_1", 0.0),
            "target_2": trade_exec.get("target_2", 0.0),
            "risk_reward": trade_exec.get("risk_reward_ratio", "1:2.0"),
            "holding_horizon": active_signal.get("expected_holding_time", "15 to 30 Minutes"),
            "key_catalysts_and_watchouts": [
                f"Track Spot CMP at ₹{cmp} relative to VWAP {active_signal.get('indicators', {}).get('vwap')}",
                f"Monitor UK FTSE and European opening at 1:00 PM IST ({uk_stance})",
                "Ensure strict discipline on Stop Loss; exit if momentum breaks trend ribbon"
            ]
        }
