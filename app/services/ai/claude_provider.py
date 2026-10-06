import base64
import json
import logging
from typing import List, Dict, Any, Optional
import httpx

from app.services.ai.base import AIVisionProvider
from app.services.ai.prompts import AI_CHART_SYSTEM_PROMPT
from app.config import settings

logger = logging.getLogger(__name__)

class ClaudeProvider(AIVisionProvider):
    def __init__(self, api_key: Optional[str] = None, model: Optional[str] = None):
        self.api_key = api_key or settings.ANTHROPIC_API_KEY
        self.model = model or settings.ANTHROPIC_MODEL or "claude-3-5-sonnet-20241022"

    async def analyze_chart(
        self,
        image_paths: List[str],
        timeframes: List[str],
        symbol: str,
        market_info: Dict[str, Any],
        notes: Optional[str] = None
    ) -> Dict[str, Any]:
        if not self.api_key:
            raise ValueError("Anthropic API key not configured")

        content = []
        for path in image_paths:
            try:
                with open(path, "rb") as img_f:
                    data = base64.b64encode(img_f.read()).decode("utf-8")
                mime = "image/png" if path.lower().endswith(".png") else "image/jpeg"
                content.append({
                    "type": "image",
                    "source": {
                        "type": "base64",
                        "media_type": mime,
                        "data": data
                    }
                })
            except Exception as e:
                logger.error(f"Failed to read image at {path}: {e}")

        content.append({
            "type": "text",
            "text": f"Analyze technical chart for {symbol}.\n"
                    f"Uploaded Timeframes: {', '.join(timeframes)}\n"
                    f"Market Details: {json.dumps(market_info)}\n"
                    f"User Notes: {notes or 'None'}\n"
                    "Return ONLY valid JSON conforming to the requested schema."
        })

        payload = {
            "model": self.model,
            "max_tokens": 3000,
            "system": AI_CHART_SYSTEM_PROMPT,
            "messages": [
                {"role": "user", "content": content}
            ],
            "temperature": 0.2
        }

        async with httpx.AsyncClient(timeout=60.0) as client:
            resp = await client.post(
                "https://api.anthropic.com/v1/messages",
                headers={
                    "x-api-key": self.api_key,
                    "anthropic-version": "2023-06-01",
                    "content-type": "application/json"
                },
                json=payload
            )
            if resp.status_code != 200:
                raise RuntimeError(f"Anthropic API error ({resp.status_code}): {resp.text}")

            result = resp.json()
            text_blocks = [b["text"] for b in result.get("content", []) if b.get("type") == "text"]
            full_text = "\n".join(text_blocks).strip()
            if full_text.startswith("```json"):
                full_text = full_text[7:]
            if full_text.startswith("```"):
                full_text = full_text[3:]
            if full_text.endswith("```"):
                full_text = full_text[:-3]
            return json.loads(full_text.strip())
