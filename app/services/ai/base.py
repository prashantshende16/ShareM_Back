from abc import ABC, abstractmethod
from typing import List, Dict, Any, Optional

class AIVisionProvider(ABC):
    @abstractmethod
    async def analyze_chart(
        self,
        image_paths: List[str],
        timeframes: List[str],
        symbol: str,
        market_info: Dict[str, Any],
        notes: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Analyze one or more chart screenshots and return structured technical analysis dictionary.
        Must conform to probabilistic, non-guaranteed scenario format.
        """
        pass
