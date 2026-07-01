"""Shared Gemini client helper."""
from google import genai

_client = None


def get_gemini_client():
    global _client
    if _client is None:
        _client = genai.Client()
    return _client
