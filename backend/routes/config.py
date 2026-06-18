from fastapi import APIRouter
from pydantic import BaseModel
from backend.services.config import load_config, save_config, get_config_for_client
from backend.services.mock_db import mock_db

router = APIRouter(prefix="/api", tags=["config"])


class ConfigModel(BaseModel):
    developer_token: str = ""
    client_id: str = ""
    client_secret: str = ""
    refresh_token: str = ""
    customer_id: str = ""
    login_customer_id: str = ""
    gemini_api_key: str = ""
    mock_mode: bool = True
    safe_mode: bool = True
    # OAuth app credentials
    google_client_id: str = ""
    google_client_secret: str = ""
    google_developer_token: str = ""
    meta_app_id: str = ""
    meta_app_secret: str = ""
    redirect_base_url: str = ""

    class Config:
        extra = "allow"


@router.get("/config")
def get_config():
    return get_config_for_client()


@router.post("/config")
def update_config(new_config: ConfigModel):
    current = load_config()
    data = new_config.model_dump()

    sensitive_keys = ["client_secret", "refresh_token", "gemini_api_key", "developer_token",
                      "google_client_secret", "google_developer_token", "meta_app_secret"]
    for key in sensitive_keys:
        if "●●●●" in (data.get(key) or ""):
            data[key] = current.get(key, "")

    # merge with current config so UI-only updates don't wipe other keys
    full = current.copy()
    full.update(data)
    save_config(full)

    if data["mock_mode"]:
        mock_db.add_action_log("SYSTEM", "Switched to Mock Sandbox Mode.")
    else:
        mock_db.add_action_log("SYSTEM", f"Configured Google Ads API (CID: {data.get('customer_id')}). Safe mode={'ON' if data.get('safe_mode') else 'OFF'}.")

    return {"status": "success", "message": "Configuration updated successfully."}
