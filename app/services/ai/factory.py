import logging
from app.config import settings
from app.services.ai.base import AIVisionProvider
from app.services.ai.openai_provider import OpenAIProvider
from app.services.ai.gemini_provider import GeminiProvider
from app.services.ai.claude_provider import ClaudeProvider
from app.services.ai.mock_provider import MockProvider

logger = logging.getLogger(__name__)

def get_ai_provider(provider_name: str = None) -> AIVisionProvider:
    provider = (provider_name or settings.AI_PROVIDER).lower()

    if provider == "openai":
        if settings.OPENAI_API_KEY:
            return OpenAIProvider()
        logger.warning("OpenAI API key missing, falling back to Mock Provider")
        return MockProvider()

    elif provider == "gemini":
        if settings.GEMINI_API_KEY:
            return GeminiProvider()
        logger.warning("Gemini API key missing, falling back to Mock Provider")
        return MockProvider()

    elif provider == "claude":
        if settings.ANTHROPIC_API_KEY:
            return ClaudeProvider()
        logger.warning("Anthropic API key missing, falling back to Mock Provider")
        return MockProvider()

    else:
        return MockProvider()
