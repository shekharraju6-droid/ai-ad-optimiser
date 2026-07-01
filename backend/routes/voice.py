import os
import json
import logging
import traceback
from fastapi import APIRouter, HTTPException, Request
from google import genai
from google.genai import types
from pydantic import BaseModel, Field

logger = logging.getLogger("AdOptima")

router = APIRouter(prefix="/api/voice", tags=["voice-control"])

# Initialize the Gemini Client
# (Picks up GEMINI_API_KEY from your Railway environment variables)
client = genai.Client()

# 1. Define the JSON schema Gemini MUST respond with
class VoiceActionResponse(BaseModel):
    action: str = Field(
        description=(
            "The matching UI action. Supported values: "
            "'REFRESH_METRICS' (parameters: timeframe), "
            "'SWITCH_TAB' or 'NAVIGATE' (parameters: tab_id or module_name), "
            "'OPEN_MODAL' (parameters: modal_type), "
            "'OPEN_ACCOUNT' or 'OPEN_DASHBOARD' (parameters: account_name, module), "
            "'SYNC_LEADS', "
            "'TOGGLE_LIVE_MODE' (parameters: platform), "
            "'CREATE_INVOICE' (parameters: client_name), "
            "'SHOW_OVERDUE'"
        )
    )
    target_module: str = Field(description="The module context: 'revenueops', 'adpulse', 'insightdesk', or 'global'")
    parameters: dict = Field(default={}, description="Key-value pairs extracted from speech (e.g., {'timeframe': '30_days', 'tab_id': 'billing', 'client_name': 'Acme Corp'})")


def _build_voice_schema():
    """Return a Gemini-compatible JSON schema dict from the Pydantic model.

    Gemini's Developer API rejects schemas that contain 'additionalProperties: false'.
    Pydantic emits that by default, so we strip it and mark the schema as permissive.
    """
    schema = VoiceActionResponse.model_json_schema()

    def _strip_additional_properties(obj):
        if isinstance(obj, dict):
            if "additionalProperties" in obj:
                del obj["additionalProperties"]
            for v in obj.values():
                _strip_additional_properties(v)
        elif isinstance(obj, list):
            for item in obj:
                _strip_additional_properties(item)

    _strip_additional_properties(schema)
    # Do NOT re-add 'additionalProperties'. Gemini Developer API rejects
    # any schema that contains this key (True or False).
    return schema


class VoiceCommandRequest(BaseModel):
    text: str


# 2. The API endpoint handling the spoken (now transcribed) command
@router.post("/command")
async def process_voice_command(request: Request):
    try:
        body = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Request must be JSON with a 'text' field")

    text = (body.get("text") or "").strip()
    if not text:
        raise HTTPException(status_code=400, detail="No command text provided")

    logger.info(f"[Rudra] received text command: {text[:200]}")

    try:
        response = client.models.generate_content(
            model='gemini-2.5-flash',
            contents=text,
            config=types.GenerateContentConfig(
                response_mime_type="application/json",
                response_schema=_build_voice_schema(),
                system_instruction=(
                    "You are Rudra, the custom voice-activated command center for this dashboard. "
                    "The user will address you as Rudra. Your only job is to listen to the user's voice "
                    "instructions, ignore your name prefix if spoken, and translate the request strictly "
                    "into the required JSON schema structure. Do not chat or reply with text."
                )
            ),
        )
        logger.info(f"[Rudra] Gemini raw response: {response.text[:500] if hasattr(response, 'text') else 'NO TEXT'}")

        parsed = json.loads(response.text)
        logger.info(f"[Rudra] parsed action: {parsed.get('action')} module: {parsed.get('target_module')}")
        return parsed

    except Exception as e:
        logger.error(f"[Rudra] command failed: {e}", exc_info=True)
        tb = traceback.format_exc()
        print(f"[Rudra] Voice command error traceback:\n{tb}")
        msg = str(e)
        if "503" in msg or "UNAVAILABLE" in msg or "high demand" in msg:
            raise HTTPException(status_code=503, detail="Gemini is temporarily overloaded. Please wait a few seconds and try again.")
        raise HTTPException(status_code=500, detail=msg)
