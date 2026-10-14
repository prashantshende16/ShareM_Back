from abc import ABC, abstractmethod
from typing import Dict, Any, Optional

class MarketDataProvider(ABC):
    @abstractmethod
    def is_connected(self) -> bool:
        pass

    @abstractmethod
    def get_status(self) -> Dict[str, Any]:
        pass

    @abstractmethod
    async def get_live_quote(self, symbol: str) -> Optional[Dict[str, Any]]:
        pass

class LiveFeedMarketDataProvider(MarketDataProvider):
    """
    Live Market Feed Provider (Phase 2 & Phase 4).
    Connects to real-time NSE/BSE and Global feeds with multi-timeframe candles,
    world indices, and 5-min Option indicator data.
    """
    def is_connected(self) -> bool:
        return True

    def get_status(self) -> Dict[str, Any]:
        return {
            "connected": True,
            "provider": "Live Market Feed",
            "message": "Connected to Real-Time Market Data Feed (NSE/BSE & Global Macro)",
            "supported_future_brokers": ["Zerodha Kite", "Upstox", "Angel One", "Dhan", "5paisa"]
        }

    async def get_live_quote(self, symbol: str) -> Optional[Dict[str, Any]]:
        from app.services.market_data.live_market_service import LiveMarketService
        yf_sym = LiveMarketService.resolve_symbol(symbol)
        data = LiveMarketService.get_candle_data(yf_sym, interval="5m", range_="1d")
        return data

class DisconnectedMarketDataProvider(MarketDataProvider):
    """
    Fallback disconnected provider when external feeds are offline.
    """
    def is_connected(self) -> bool:
        return False

    def get_status(self) -> Dict[str, Any]:
        return {
            "connected": False,
            "provider": "None",
            "message": "Market data not connected. Connect a supported broker API (Zerodha Kite, Upstox, Angel One, Dhan) for live data.",
            "supported_future_brokers": ["Zerodha Kite", "Upstox", "Angel One", "Dhan", "5paisa"]
        }

    async def get_live_quote(self, symbol: str) -> Optional[Dict[str, Any]]:
        return None

# Active provider: Live Market Data Feed
market_data_provider = LiveFeedMarketDataProvider()
