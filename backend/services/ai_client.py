"""Shared Gemini client helper."""
from google import genai

_client = None


def get_gemini_client():
    global _client
    if _client is None:
        from backend.services.config import load_config
        config = load_config()
        api_key = config.get("gemini_api_key")
        if api_key:
            _client = genai.Client(api_key=api_key)
        else:
            _client = genai.Client()
    return _client

