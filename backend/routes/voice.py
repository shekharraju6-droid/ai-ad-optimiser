import os
import json
from fastapi import APIRouter, UploadFile, File, HTTPException
from google import genai
from google.genai import types
from pydantic import BaseModel, Field

router = APIRouter(prefix="/api/voice", tags=["voice-control"])

# Initialize the Gemini Client
# (Picks up GEMINI_API_KEY from your Railway environment variables)
client = genai.Client()

# 1. Define the JSON schema Gemini MUST respond with
class VoiceActionResponse(BaseModel):
    action: str = Field(description="The matching UI action: 'REFRESH_METRICS', 'SWITCH_TAB', 'OPEN_MODAL'")
    target_module: str = Field(description="The module context: 'revenueops', 'adpulse', 'insightdesk'")
    parameters: dict = Field(default={}, description="Key-value pairs extracted from speech (e.g., {'timeframe': '30_days', 'tab_id': 'billing'})")

# 2. The API endpoint handling your spoken audio file
@router.post("/command")
async def process_voice_command(file: UploadFile = File(...)):
    if not file.filename:
        raise HTTPException(status_code=400, detail="No audio file provided")
        
    try:
        # Save temporary file locally on the Railway container container instance
        temp_file_path = f"/tmp/{file.filename}"
        with open(temp_file_path, "wb") as buffer:
            buffer.write(await file.read())
            
        # Upload the audio to Google's temporary staging environment
        uploaded_audio = client.files.upload(file=temp_file_path)
        
        # Analyze the audio file using Gemini
        response = client.models.generate_content(
            model='gemini-2.5-flash',
            contents=[
                uploaded_audio,
                "Analyze the user's vocal command and output the structured UI action sequence."
            ],
            config=types.GenerateContentConfig(
                response_mime_type="application/json",
                response_schema=VoiceActionResponse,
                system_instruction=(
                    "You are the structural router for an internal enterprise dashboard app. "
                    "Translate vocal requests strictly into the required JSON schema. Do not chat."
                )
            ),
        )
        
        # Clean up temporary storage assets
        client.files.delete(name=uploaded_audio.name)
        os.remove(temp_file_path)
        
        # Parse the stringified JSON back into a true dictionary to return to frontend
        return json.loads(response.text)
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
