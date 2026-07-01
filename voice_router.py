import os
import tempfile
from google import genai
from google.genai import types
from pydantic import BaseModel, Field

# 1. Initialize the client
client = genai.Client()

# 2. Define exactly what data your dashboard needs to take action
class DashboardCommand(BaseModel):
    action: str = Field(
        description="The main action to take. Allowed values: 'GENERATE_REPORT', 'SWITCH_DASHBOARD', 'REFRESH_ADS'."
    )
    target_platform: str = Field(
        description="The ad platform or source, e.g., 'facebook', 'google', 'all', or 'none' if not applicable."
    )
    timeframe: str = Field(
        description="The requested time range, e.g., 'today', 'yesterday', 'last_7_days'. Default to 'today' if unclear."
    )
    visual_layout: str = Field(
        description="The type of visual component to show, e.g., 'grid_view', 'bar_chart', 'table_view'."
    )


def process_voice_command(audio_bytes: bytes) -> DashboardCommand:
    """Process raw audio bytes and return a structured dashboard command."""
    
    # Save bytes to a temporary file for Gemini upload
    with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as tmp:
        tmp.write(audio_bytes)
        tmp_path = tmp.name
    
    try:
        # Upload the audio file to Google's temporary staging environment
        uploaded_file = client.files.upload(file=tmp_path)
        
        # Request analysis from Gemini
        response = client.models.generate_content(
            model='gemini-2.5-flash',
            contents=[
                uploaded_file,
                "Listen carefully to the audio instruction and extract the dashboard configuration."
            ],
            config=types.GenerateContentConfig(
                # Force the response to be strict JSON matching our Pydantic structure
                response_mime_type="application/json",
                response_schema=DashboardCommand,
                
                # Put Gemini in 'Command Center' mode
                system_instruction=(
                    "You are the silent brain of a live advertising dashboard command center. "
                    "Your only job is to listen to the user's voice instructions and translate "
                    "them into the requested JSON schema structure. Do not include any greeting, "
                    "conversational text, or explanations. Only output the raw JSON."
                )
            ),
        )
        
        # Clean up the uploaded file from Google Cloud staging
        client.files.delete(name=uploaded_file.name)
        
        # Gemini returns the parsed Pydantic object when response_schema is used
        if response.parsed:
            return response.parsed
        
        # Fallback: parse JSON string if parsed is not available
        import json
        data = json.loads(response.text)
        return DashboardCommand(**data)
    finally:
        os.unlink(tmp_path)


def execute_command(command: DashboardCommand) -> dict:
    """Map a voice command to business logic and return execution payload."""
    action = command.action.upper()
    
    if action == "REFRESH_ADS":
        return {
            "status": "ok",
            "message": f"Refresh ads triggered for {command.target_platform}.",
            "command": command.model_dump(),
            "data": {
                "platform": command.target_platform,
                "ads": [],
                "note": "Connect live ad API here.",
                "timestamp": None,
            }
        }
    
    if action == "GENERATE_REPORT":
        return {
            "status": "ok",
            "message": f"Generate report triggered for {command.target_platform} ({command.timeframe}).",
            "command": command.model_dump(),
            "data": {
                "platform": command.target_platform,
                "timeframe": command.timeframe,
                "visual_layout": command.visual_layout,
                "rows": []
            }
        }
    
    if action == "SWITCH_DASHBOARD":
        return {
            "status": "ok",
            "message": f"Switch dashboard to {command.target_platform}.",
            "command": command.model_dump(),
            "data": {
                "target_module": command.target_platform,
                "timeframe": command.timeframe,
                "visual_layout": command.visual_layout,
            }
        }
    
    return {
        "status": "unknown_action",
        "message": f"Unknown action: {action}",
        "command": command.model_dump(),
        "data": {}
    }


if __name__ == "__main__":
    # Make sure you have an actual audio file named 'command.mp3' in your folder!
    TEST_AUDIO = "command.mp3" 
    
    if os.path.exists(TEST_AUDIO):
        with open(TEST_AUDIO, "rb") as f:
            audio_bytes = f.read()
        parsed_command = process_voice_command(audio_bytes)
        print("\n--- Parsed Command ---")
        print(parsed_command.model_dump_json(indent=2))
        print("\n--- Execution Result ---")
        print(json.dumps(execute_command(parsed_command), indent=2))
        print("------------------------------")
    else:
        print(f"\nPlace a test audio file named '{TEST_AUDIO}' in this folder to run the test!")
