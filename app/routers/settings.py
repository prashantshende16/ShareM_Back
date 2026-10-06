from fastapi import APIRouter, HTTPException
from app.config import settings
from app.schemas import SettingsUpdate, SettingsStatusResponse
from app.services.ai.factory import get_ai_provider
from app.services.market_data.provider import market_data_provider

router = APIRouter(prefix="/settings", tags=["Settings"])

@router.get("", response_model=SettingsStatusResponse)
def get_settings():
    return SettingsStatusResponse(
        current_provider=settings.AI_PROVIDER,
        available_providers=["openai", "gemini", "claude", "mock"],
        is_openai_configured=bool(settings.OPENAI_API_KEY),
        is_gemini_configured=bool(settings.GEMINI_API_KEY),
        is_anthropic_configured=bool(settings.ANTHROPIC_API_KEY),
        market_data_connected=market_data_provider.is_connected(),
        market_data_status=market_data_provider.get_status().get("message", "Market data not connected")
    )

@router.post("", response_model=SettingsStatusResponse)
def update_settings(data: SettingsUpdate):
    if data.ai_provider:
        p = data.ai_provider.lower()
        if p not in ["openai", "gemini", "claude", "mock"]:
            raise HTTPException(status_code=400, detail="Invalid provider. Choose openai, gemini, claude, or mock")
        settings.AI_PROVIDER = p

    if data.openai_api_key is not None:
        settings.OPENAI_API_KEY = data.openai_api_key
    if data.openai_model is not None:
        settings.OPENAI_MODEL = data.openai_model

    if data.gemini_api_key is not None:
        settings.GEMINI_API_KEY = data.gemini_api_key
    if data.gemini_model is not None:
        settings.GEMINI_MODEL = data.gemini_model

    if data.anthropic_api_key is not None:
        settings.ANTHROPIC_API_KEY = data.anthropic_api_key
    if data.anthropic_model is not None:
        settings.ANTHROPIC_MODEL = data.anthropic_model

    return get_settings()

@router.post("/test-connection")
async def test_ai_connection():
    provider = get_ai_provider()
    try:
        # Run a lightweight dry test with mock input
        res = await provider.analyze_chart(
            image_paths=[],
            timeframes=["15 Minute"],
            symbol="NIFTY 50",
            market_info={"current_price": 25000.0},
            notes="Testing provider connectivity"
        )
        return {
            "status": "success",
            "provider": settings.AI_PROVIDER,
            "message": f"Successfully verified {settings.AI_PROVIDER} provider connectivity.",
            "test_scenario": res.get("primary_scenario")
        }
    except Exception as e:
        return {
            "status": "error",
            "provider": settings.AI_PROVIDER,
            "message": f"Connection test failed: {str(e)}"
        }
