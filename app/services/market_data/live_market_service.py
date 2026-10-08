import os
import json
import logging
import asyncio
import urllib.request
import xml.etree.ElementTree as ET
from typing import Dict, Any, List, Optional
from PIL import Image, ImageDraw, ImageFont

logger = logging.getLogger(__name__)

# Symbol mapping to Yahoo Finance symbols
SYMBOL_MAPPINGS = {
    "NIFTY": "^NSEI",
    "NIFTY 50": "^NSEI",
    "BANKNIFTY": "^NSEBANK",
    "FINNIFTY": "NIFTY_FIN_SERVICE.NS",
    "SENSEX": "^BSESN",
    "RELIANCE": "RELIANCE.NS",
    "HDFCBANK": "HDFCBANK.NS",
    "ICICIBANK": "ICICIBANK.NS",
    "INFY": "INFY.NS",
    "TCS": "TCS.NS",
    "SBIN": "SBIN.NS",
    "KOTAKBANK": "KOTAKBANK.NS",
    "AXISBANK": "AXISBANK.NS",
    "LT": "LT.NS",
    "ITC": "ITC.NS"
}

# Major global market indices to track
GLOBAL_INDICES = [
    {"name": "Dow Jones (US)", "symbol": "^DJI", "region": "US"},
    {"name": "Nasdaq (US)", "symbol": "^IXIC", "region": "US"},
    {"name": "S&P 500 (US)", "symbol": "^GSPC", "region": "US"},
    {"name": "Nikkei 225 (Japan)", "symbol": "^N225", "region": "Asia"},
    {"name": "FTSE 100 (UK)", "symbol": "^FTSE", "region": "Europe"},
    {"name": "Crude Oil WTI", "symbol": "CL=F", "region": "Commodity"},
    {"name": "India VIX", "symbol": "^INDIAVIX", "region": "India"},
]

# Nifty 50 Top Heavyweight Movers & Bank Contributors
NIFTY_HEAVYWEIGHTS = [
    {"name": "HDFC Bank", "symbol": "HDFCBANK.NS", "weight": "11.5%", "sector": "Banking"},
    {"name": "Reliance Ind", "symbol": "RELIANCE.NS", "weight": "9.2%", "sector": "Energy"},
    {"name": "ICICI Bank", "symbol": "ICICIBANK.NS", "weight": "7.8%", "sector": "Banking"},
    {"name": "Infosys", "symbol": "INFY.NS", "weight": "5.4%", "sector": "IT"},
    {"name": "TCS", "symbol": "TCS.NS", "weight": "3.9%", "sector": "IT"},
    {"name": "State Bank of India", "symbol": "SBIN.NS", "weight": "3.1%", "sector": "Banking"},
    {"name": "Larsen & Toubro", "symbol": "LT.NS", "weight": "4.2%", "sector": "Infrastructure"},
    {"name": "Axis Bank", "symbol": "AXISBANK.NS", "weight": "3.3%", "sector": "Banking"},
]

def fetch_json(url: str, timeout: int = 6) -> Optional[Dict[str, Any]]:
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"})
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode())
    except Exception as e:
        logger.warning(f"Error fetching URL {url}: {e}")
        return None

class LiveMarketService:
    @staticmethod
    def resolve_symbol(symbol: str) -> str:
        clean = symbol.strip().upper()
        return SYMBOL_MAPPINGS.get(clean, f"{clean}.NS" if not clean.startswith("^") and not clean.endswith(".NS") else clean)

    @classmethod
    def get_candle_data(cls, yf_symbol: str, interval: str = "5m", range_: str = "1d") -> Optional[Dict[str, Any]]:
        url = f"https://query1.finance.yahoo.com/v8/finance/chart/{yf_symbol}?interval={interval}&range={range_}"
        data = fetch_json(url)
        if not data or "chart" not in data or not data["chart"].get("result"):
            return None

        result = data["chart"]["result"][0]
        meta = result.get("meta", {})
        timestamps = result.get("timestamp", [])
        quote = result.get("indicators", {}).get("quote", [{}])[0]

        opens = quote.get("open", [])
        highs = quote.get("high", [])
        lows = quote.get("low", [])
        closes = quote.get("close", [])
        volumes = quote.get("volume", [])

        valid_candles = []
        for i in range(len(timestamps)):
            if (
                i < len(opens) and opens[i] is not None
                and i < len(highs) and highs[i] is not None
                and i < len(lows) and lows[i] is not None
                and i < len(closes) and closes[i] is not None
            ):
                valid_candles.append({
                    "time": timestamps[i],
                    "open": round(opens[i], 2),
                    "high": round(highs[i], 2),
                    "low": round(lows[i], 2),
                    "close": round(closes[i], 2),
                    "volume": volumes[i] if i < len(volumes) and volumes[i] is not None else 0
                })

        cmp = meta.get("regularMarketPrice") or (valid_candles[-1]["close"] if valid_candles else 0.0)
        prev_close = meta.get("chartPreviousClose") or cmp

        # Calculate simple technical metrics
        closes_list = [c["close"] for c in valid_candles]
        rsi_14 = cls.calculate_rsi(closes_list, 14) if len(closes_list) >= 15 else None
        ema_20 = cls.calculate_ema(closes_list, 20) if len(closes_list) >= 20 else None

        change = round(cmp - prev_close, 2)
        change_pct = round((change / prev_close) * 100, 2) if prev_close else 0.0

        return {
            "symbol": yf_symbol,
            "current_price": round(cmp, 2),
            "previous_close": round(prev_close, 2),
            "change": change,
            "change_pct": change_pct,
            "day_high": meta.get("regularMarketDayHigh"),
            "day_low": meta.get("regularMarketDayLow"),
            "interval": interval,
            "candles": valid_candles[-60:],  # keep last 60 for analysis/chart
            "rsi_14": rsi_14,
            "ema_20": ema_20
        }

    @staticmethod
    def calculate_rsi(prices: List[float], period: int = 14) -> Optional[float]:
        if len(prices) <= period:
            return None
        deltas = [prices[i] - prices[i - 1] for i in range(1, len(prices))]
        gains = [d if d > 0 else 0.0 for d in deltas]
        losses = [-d if d < 0 else 0.0 for d in deltas]

        avg_gain = sum(gains[:period]) / period
        avg_loss = sum(losses[:period]) / period

        for i in range(period, len(deltas)):
            avg_gain = (avg_gain * (period - 1) + gains[i]) / period
            avg_loss = (avg_loss * (period - 1) + losses[i]) / period

        if avg_loss == 0:
            return 100.0
        rs = avg_gain / avg_loss
        return round(100.0 - (100.0 / (1.0 + rs)), 1)

    @staticmethod
    def calculate_ema(prices: List[float], period: int = 20) -> Optional[float]:
        if len(prices) < period:
            return None
        multiplier = 2 / (period + 1)
        ema = sum(prices[:period]) / period
        for price in prices[period:]:
            ema = (price - ema) * multiplier + ema
        return round(ema, 2)

    @classmethod
    def get_multi_timeframe_data(cls, symbol: str) -> Dict[str, Any]:
        yf_symbol = cls.resolve_symbol(symbol)
        timeframes = [
            {"label": "1 Minute", "interval": "1m", "range": "1d"},
            {"label": "5 Minute", "interval": "5m", "range": "1d"},
            {"label": "15 Minute", "interval": "15m", "range": "5d"},
            {"label": "30 Minute", "interval": "30m", "range": "5d"},
            {"label": "1 Hour", "interval": "1h", "range": "1mo"},
        ]

        results = {}
        base_info = None

        for tf in timeframes:
            data = cls.get_candle_data(yf_symbol, interval=tf["interval"], range_=tf["range"])
            if data:
                results[tf["label"]] = data
                if not base_info:
                    base_info = {
                        "symbol": symbol,
                        "yf_symbol": yf_symbol,
                        "current_price": data["current_price"],
                        "previous_close": data["previous_close"],
                        "change": data["change"],
                        "change_pct": data["change_pct"],
                        "day_high": data["day_high"],
                        "day_low": data["day_low"]
                    }

        return {
            "base_info": base_info or {
                "symbol": symbol,
                "yf_symbol": yf_symbol,
                "current_price": 0.0,
                "change": 0.0,
                "change_pct": 0.0
            },
            "timeframes": results
        }

    @classmethod
    def get_global_market_overview(cls) -> Dict[str, Any]:
        overview = []
        positive_count = 0
        negative_count = 0

        for item in GLOBAL_INDICES:
            try:
                data = cls.get_candle_data(item["symbol"], interval="5m", range_="1d")
                if data:
                    chg_pct = data["change_pct"]
                    if chg_pct > 0.1:
                        positive_count += 1
                    elif chg_pct < -0.1:
                        negative_count += 1
                    overview.append({
                        "name": item["name"],
                        "symbol": item["symbol"],
                        "region": item["region"],
                        "price": data["current_price"],
                        "change": data["change"],
                        "change_pct": chg_pct,
                        "sentiment": "bullish" if chg_pct > 0 else "bearish" if chg_pct < 0 else "neutral"
                    })
            except Exception as e:
                logger.warning(f"Error fetching global index {item['name']}: {e}")

        # Overall global bias
        if positive_count > negative_count + 1:
            global_sentiment = "Bullish / Risk-On"
        elif negative_count > positive_count + 1:
            global_sentiment = "Bearish / Risk-Off"
        else:
            global_sentiment = "Mixed / Neutral Consolidation"

        return {
            "global_sentiment": global_sentiment,
            "indices": overview
        }

    @classmethod
    def get_heavyweights_overview(cls) -> List[Dict[str, Any]]:
        heavyweights = []
        for stock in NIFTY_HEAVYWEIGHTS:
            try:
                data = cls.get_candle_data(stock["symbol"], interval="5m", range_="1d")
                if data:
                    heavyweights.append({
                        "name": stock["name"],
                        "symbol": stock["symbol"],
                        "weight": stock["weight"],
                        "sector": stock["sector"],
                        "price": data["current_price"],
                        "change": data["change"],
                        "change_pct": data["change_pct"],
                        "rsi_14": data.get("rsi_14")
                    })
            except Exception as e:
                logger.warning(f"Error fetching stock {stock['name']}: {e}")
        return heavyweights

    @classmethod
    def get_market_incidents_news(cls) -> List[Dict[str, str]]:
        url = "https://news.google.com/rss/search?q=NIFTY+Indian+stock+market+crash+rally&hl=en-IN&gl=IN&ceid=IN:en"
        news_items = []
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"})
            with urllib.request.urlopen(req, timeout=5) as resp:
                xml_data = resp.read()
                root = ET.fromstring(xml_data)
                for item in root.findall(".//item")[:6]:
                    title = item.find("title").text if item.find("title") is not None else ""
                    pub_date = item.find("pubDate").text if item.find("pubDate") is not None else ""
                    link = item.find("link").text if item.find("link") is not None else ""
                    if title:
                        news_items.append({
                            "title": title,
                            "date": pub_date,
                            "url": link
                        })
        except Exception as e:
            logger.warning(f"Error fetching market news RSS: {e}")
        return news_items

    @classmethod
    def render_candlestick_chart(
        cls,
        candles: List[Dict[str, Any]],
        title: str,
        output_path: str,
        width: int = 800,
        height: int = 400
    ) -> bool:
        """
        Renders a clean financial candlestick chart image directly via Pillow.
        Saves to output_path so AI Vision models can analyze genuine chart visuals.
        """
        if not candles:
            return False

        try:
            # Create dark canvas
            img = Image.new("RGB", (width, height), color=(15, 23, 42))  # slate-900
            draw = ImageDraw.Draw(img)

            # Padding
            pad_left = 60
            pad_right = 80
            pad_top = 40
            pad_bottom = 40

            chart_w = width - pad_left - pad_right
            chart_h = height - pad_top - pad_bottom

            all_highs = [c["high"] for c in candles]
            all_lows = [c["low"] for c in candles]
            min_p = min(all_lows)
            max_p = max(all_highs)
            p_range = max(1.0, max_p - min_p)

            # Grid lines
            grid_steps = 5
            for i in range(grid_steps + 1):
                y = pad_top + int(chart_h * (i / grid_steps))
                price_lvl = round(max_p - (p_range * (i / grid_steps)), 2)
                draw.line([(pad_left, y), (width - pad_right, y)], fill=(30, 41, 59), width=1)
                draw.text((width - pad_right + 8, y - 6), f"{price_lvl}", fill=(148, 163, 184))

            # Draw Candles
            n = len(candles)
            candle_w = max(2, int((chart_w / max(1, n)) * 0.75))
            step_x = chart_w / max(1, n)

            for idx, c in enumerate(candles):
                cx = pad_left + int(idx * step_x + step_x / 2)
                o_y = pad_top + int(((max_p - c["open"]) / p_range) * chart_h)
                c_y = pad_top + int(((max_p - c["close"]) / p_range) * chart_h)
                h_y = pad_top + int(((max_p - c["high"]) / p_range) * chart_h)
                l_y = pad_top + int(((max_p - c["low"]) / p_range) * chart_h)

                is_green = c["close"] >= c["open"]
                color = (34, 197, 94) if is_green else (239, 68, 68)  # green-500 or red-500

                # High-Low Wick
                draw.line([(cx, h_y), (cx, l_y)], fill=color, width=1)

                # Candle Body
                top_y = min(o_y, c_y)
                bot_y = max(o_y, c_y)
                if bot_y - top_y < 1:
                    bot_y = top_y + 1

                left_x = cx - candle_w // 2
                right_x = cx + candle_w // 2
                draw.rectangle([left_x, top_y, right_x, bot_y], fill=color)

            # Title
            draw.text((pad_left, 12), title, fill=(248, 250, 252))

            # Current price badge
            last_close = candles[-1]["close"]
            cur_color = (34, 197, 94) if candles[-1]["close"] >= candles[0]["open"] else (239, 68, 68)
            draw.text((width - pad_right - 120, 12), f"CMP: {last_close}", fill=cur_color)

            os.makedirs(os.path.dirname(output_path), exist_ok=True)
            img.save(output_path, "PNG")
            return True
        except Exception as e:
            logger.error(f"Failed to render chart image: {e}")
            return False

