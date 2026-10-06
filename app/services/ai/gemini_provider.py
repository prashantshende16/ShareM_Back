import base64
import json
import logging
from typing import List, Dict, Any, Optional
import httpx

from app.services.ai.base import AIVisionProvider
from app.services.ai.prompts import AI_CHART_SYSTEM_PROMPT
from app.config import settings

logger = logging.getLogger(__name__)

class GeminiProvider(AIVisionProvider):
    def __init__(self, api_key: Optional[str] = None, model: Optional[str] = None):
        self.api_key = api_key or settings.GEMINI_API_KEY
        self.model = model or settings.GEMINI_MODEL or "gemini-1.5-pro"

    async def analyze_chart(
        self,
        image_paths: List[str],
        timeframes: List[str],
        symbol: str,
        market_info: Dict[str, Any],
        notes: Optional[str] = None
    ) -> Dict[str, Any]:
        if not self.api_key:
            raise ValueError("Gemini API key not configured")

        parts = []
        parts.append({
            "text": f"{AI_CHART_SYSTEM_PROMPT}\n\n"
                    f"Now analyze the attached charts for: {symbol}\n"
                    f"Timeframes: {', '.join(timeframes)}\n"
                    f"Market Info: {json.dumps(market_info)}\n"
                    f"Notes: {notes or 'None'}\n"
                    "Output strictly valid JSON only."
        })

        for path in image_paths:
            try:
                with open(path, "rb") as img_f:
                    data = base64.b64encode(img_f.read()).decode("utf-8")
                mime = "image/png" if path.lower().endswith(".png") else "image/jpeg"
                parts.append({
                    "inline_data": {
                        "mime_type": mime,
                        "data": data
                    }
                })
            except Exception as e:
                logger.error(f"Failed to read image at {path}: {e}")

        payload = {
            "contents": [{"parts": parts}],
            "generationConfig": {
                "response_mime_type": "application/json",
                "temperature": 0.2
            }
        }

        url = f"https://generativelanguage.googleapis.com/v1beta/models/{self.model}:generateContent?key={self.api_key}"

        async with httpx.AsyncClient(timeout=60.0) as client:
            resp = await client.post(url, json=payload)
            if resp.status_code != 200:
                raise RuntimeError(f"Gemini API error ({resp.status_code}): {resp.text}")

            res_json = resp.json()
            candidate = res_json["candidates"][0]["content"]["parts"][0]["text"]
            return json.loads(candidate)
