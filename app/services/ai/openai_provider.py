import base64
import json
import logging
from typing import List, Dict, Any, Optional
import httpx

from app.services.ai.base import AIVisionProvider
from app.services.ai.prompts import AI_CHART_SYSTEM_PROMPT
from app.config import settings

logger = logging.getLogger(__name__)

class OpenAIProvider(AIVisionProvider):
    def __init__(self, api_key: Optional[str] = None, model: Optional[str] = None):
        self.api_key = api_key or settings.OPENAI_API_KEY
        self.model = model or settings.OPENAI_MODEL or "gpt-4o"

    async def analyze_chart(
        self,
        image_paths: List[str],
        timeframes: List[str],
        symbol: str,
        market_info: Dict[str, Any],
        notes: Optional[str] = None
    ) -> Dict[str, Any]:
        if not self.api_key:
            raise ValueError("OpenAI API key not configured")

        user_content = []
        user_content.append({
            "type": "text",
            "text": f"Analyze technical chart for {symbol}.\n"
                    f"Uploaded Timeframes: {', '.join(timeframes)}\n"
                    f"Market Details: {json.dumps(market_info)}\n"
                    f"User Notes: {notes or 'None'}\n"
                    "Analyze every timeframe and compare them. Return strictly valid JSON."
        })

        for path in image_paths:
            try:
                with open(path, "rb") as img_f:
                    data = base64.b64encode(img_f.read()).decode("utf-8")
                mime = "image/png" if path.lower().endswith(".png") else "image/jpeg"
                user_content.append({
                    "type": "image_url",
                    "image_url": {
                        "url": f"data:{mime};base64,{data}"
                    }
                })
            except Exception as e:
                logger.error(f"Failed to read image at {path}: {e}")

        payload = {
            "model": self.model,
            "response_format": {"type": "json_object"},
            "messages": [
                {"role": "system", "content": AI_CHART_SYSTEM_PROMPT},
                {"role": "user", "content": user_content}
            ],
            "max_tokens": 3000,
            "temperature": 0.2
        }

        async with httpx.AsyncClient(timeout=60.0) as client:
            resp = await client.post(
                "https://api.openai.com/v1/chat/completions",
                headers={
                    "Authorization": f"Bearer {self.api_key}",
                    "Content-Type": "application/json"
                },
                json=payload
            )
            if resp.status_code != 200:
                raise RuntimeError(f"OpenAI API error ({resp.status_code}): {resp.text}")

            result = resp.json()
            content = result["choices"][0]["message"]["content"]
            return json.loads(content)
