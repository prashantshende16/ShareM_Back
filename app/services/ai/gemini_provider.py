import os
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
        self.model = model or settings.GEMINI_MODEL or "gemini-3.8-flash"

    async def get_working_model(self, client: httpx.AsyncClient) -> str:
        """
        Dynamically query Gemini ListModels API to find the best available model for this key.
        """
        candidate_preference = [
            "gemini-3.8-flash",
            "gemini-3.6-flash",
            "gemini-3.5-flash",
            "gemini-3.7-flash",
            "gemini-flash-latest",
            "gemini-2.0-flash",
            "gemini-1.5-flash",
            "gemini-1.5-pro",
        ]

        try:
            list_url = f"https://generativelanguage.googleapis.com/v1beta/models?key={self.api_key}"
            resp = await client.get(list_url, timeout=10.0)
            if resp.status_code == 200:
                data = resp.json()
                available = []
                for m in data.get("models", []):
                    methods = m.get("supportedGenerationMethods", [])
                    if "generateContent" in methods:
                        m_name = m.get("name", "").replace("models/", "")
                        available.append(m_name)

                logger.info(f"Available Gemini models for key: {available}")

                # 1. If currently configured model is directly available, use it
                clean_curr = self.model.replace("models/", "")
                if clean_curr in available:
                    return clean_curr

                # 2. Pick best preference from available
                for pref in candidate_preference:
                    if pref in available:
                        logger.info(f"Selecting best available Gemini model: {pref}")
                        return pref

                # 3. If any model supports generateContent, pick the first
                if available:
                    return available[0]
        except Exception as e:
            logger.warning(f"Could not list Gemini models: {e}")

        # Default fallback
        return self.model.replace("models/", "")

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
                    "Output strictly valid JSON only matching the schema."
        })

        for path in image_paths:
            if os.path.exists(path):
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

        async with httpx.AsyncClient(timeout=60.0) as client:
            model_to_use = await self.get_working_model(client)
            candidate_models = [model_to_use]
            for m in ["gemini-3.8-flash", "gemini-3.6-flash", "gemini-3.5-flash", "gemini-3.7-flash"]:
                if m not in candidate_models:
                    candidate_models.append(m)

            last_error = None
            for m_candidate in candidate_models:
                endpoints = [
                    f"https://generativelanguage.googleapis.com/v1beta/models/{m_candidate}:generateContent?key={self.api_key}",
                    f"https://generativelanguage.googleapis.com/v1/models/{m_candidate}:generateContent?key={self.api_key}"
                ]
                for url in endpoints:
                    try:
                        resp = await client.post(url, json=payload)
                        if resp.status_code == 200:
                            res_json = resp.json()
                            candidates = res_json.get("candidates", [])
                            if candidates and "content" in candidates[0]:
                                parts_out = candidates[0]["content"].get("parts", [])
                                if parts_out and "text" in parts_out[0]:
                                    text_val = parts_out[0]["text"].strip()
                                    if text_val.startswith("```json"):
                                        text_val = text_val[7:]
                                    if text_val.startswith("```"):
                                        text_val = text_val[3:]
                                    if text_val.endswith("```"):
                                        text_val = text_val[:-3]
                                    return json.loads(text_val.strip())
                        else:
                            last_error = f"Gemini API error ({resp.status_code}) on model '{m_candidate}': {resp.text}"
                    except Exception as ex:
                        last_error = str(ex)

            raise RuntimeError(last_error or "Failed to generate content from Gemini API")
