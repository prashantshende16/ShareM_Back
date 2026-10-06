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

class DisconnectedMarketDataProvider(MarketDataProvider):
    """
    Default provider when no broker credentials are configured.
    Guarantees no fake data is generated.
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
        # Strictly never fabricate live market data
        return None

market_data_provider = DisconnectedMarketDataProvider()
