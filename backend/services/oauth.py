"""
OAuth helpers for Google Ads and Meta Marketing API.
Generates authorization URLs, exchanges codes, stores encrypted tokens,
and converts Meta short-lived tokens to long-lived tokens.

Supports per-account OAuth app overrides for different MCC setups.
"""
import json
import os
import secrets
import urllib.parse
import urllib.request
from typing import Dict, Any, Optional
from backend.services.crypto import encrypt, decrypt
from backend.services.config import load_config
from backend.db.database import SessionLocal
from backend.db.models import Account
import logging

logger = logging.getLogger("AdOptima")


def _get_account(account_id: int) -> Optional[Account]:
    db = SessionLocal()
    try:
        return db.query(Account).filter(Account.id == account_id).first()
    finally:
        db.close()


def _account_oauth(account: Optional[Account]) -> Dict[str, Any]:
    """Return effective OAuth config: account override if set, else global config."""
    cfg = load_config()
    if not account:
        return cfg
    return {
        "google_client_id": account.google_client_id or cfg.get("google_client_id", ""),
        "google_client_secret": account.google_client_secret or cfg.get("google_client_secret", ""),
        "google_developer_token": account.google_developer_token or cfg.get("google_developer_token", ""),
        "meta_app_id": account.meta_app_id or cfg.get("meta_app_id", ""),
        "meta_app_secret": account.meta_app_secret or cfg.get("meta_app_secret", ""),
        "redirect_base_url": account.redirect_base_url or cfg.get("redirect_base_url", "http://127.0.0.1:8000"),
    }


def _require(oauth_cfg: Dict[str, Any], key: str) -> str:
    val = oauth_cfg.get(key, "")
    if not val:
        raise RuntimeError(f"Missing required OAuth config: {key}")
    return val


def _redirect_base(oauth_cfg: Dict[str, Any]) -> str:
    return oauth_cfg.get("redirect_base_url", "http://127.0.0.1:8000").rstrip("/")


# ---------------------------------------------------------------------------
# Google Ads OAuth
# ---------------------------------------------------------------------------

def get_google_auth_url(account_id: int) -> str:
    """Build Google's OAuth 2.0 URL with a state param linking to the account."""
    account = _get_account(account_id)
    oauth_cfg = _account_oauth(account)
    client_id = _require(oauth_cfg, "google_client_id")
    base = _redirect_base(oauth_cfg)
    redirect_uri = f"{base}/api/oauth/google/callback"
    state = secrets.token_urlsafe(16)
    payload = {"account_id": account_id, "platform": "google", "token": state}
    from base64 import urlsafe_b64encode
    state_b64 = urlsafe_b64encode(json.dumps(payload).encode()).decode().rstrip("=")
    params = {
        "client_id": client_id,
        "redirect_uri": redirect_uri,
        "response_type": "code",
        "scope": "https://www.googleapis.com/auth/adwords",
        "access_type": "offline",
        "prompt": "consent",
        "state": state_b64,
    }
    return "https://accounts.google.com/o/oauth2/v2/auth?" + urllib.parse.urlencode(params)


def exchange_google_code(code: str, redirect_uri: str, account_id: int) -> Optional[Dict[str, Any]]:
    account = _get_account(account_id)
    oauth_cfg = _account_oauth(account)
    client_id = _require(oauth_cfg, "google_client_id")
    client_secret = _require(oauth_cfg, "google_client_secret")
    data = urllib.parse.urlencode({
        "code": code,
        "client_id": client_id,
        "client_secret": client_secret,
        "redirect_uri": redirect_uri,
        "grant_type": "authorization_code",
    }).encode()
    req = urllib.request.Request(
        "https://oauth2.googleapis.com/token",
        data=data,
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req) as resp:
            token_data = json.loads(resp.read().decode())
            return token_data
    except Exception as e:
        logger.error(f"Google token exchange failed: {e}")
        return None


def build_google_credentials(token_data: Dict[str, Any], account_id: int) -> Optional[str]:
    """Return encrypted JSON string suitable for GoogleAdsConnector."""
    account = _get_account(account_id)
    oauth_cfg = _account_oauth(account)
    client_id = oauth_cfg.get("google_client_id") or oauth_cfg.get("client_id", "")
    client_secret = oauth_cfg.get("google_client_secret") or oauth_cfg.get("client_secret", "")
    developer_token = oauth_cfg.get("google_developer_token") or oauth_cfg.get("developer_token", "")
    refresh_token = token_data.get("refresh_token") or token_data.get("access_token")
    if not refresh_token:
        return None
    login_customer_id = ""
    if account:
        login_customer_id = (account.google_login_customer_id or "").replace("-", "")
    creds = {
        "developer_token": developer_token,
        "client_id": client_id,
        "client_secret": client_secret,
        "refresh_token": refresh_token,
        "login_customer_id": login_customer_id,
    }
    return encrypt(json.dumps(creds))


# ---------------------------------------------------------------------------
# Google Sheets OAuth (for Shyam Steel user Gmail account)
# ---------------------------------------------------------------------------

def get_sheets_auth_url(account_id: int) -> str:
    """Build Google's OAuth URL for Sheets access via user's Gmail account."""
    account = _get_account(account_id)
    oauth_cfg = _account_oauth(account)
    client_id = _require(oauth_cfg, "google_client_id")
    base = _redirect_base(oauth_cfg)
    redirect_uri = f"{base}/api/oauth/sheets/callback"
    state = secrets.token_urlsafe(16)
    payload = {"account_id": account_id, "platform": "sheets", "token": state}
    from base64 import urlsafe_b64encode
    state_b64 = urlsafe_b64encode(json.dumps(payload).encode()).decode().rstrip("=")
    params = {
        "client_id": client_id,
        "redirect_uri": redirect_uri,
        "response_type": "code",
        "scope": "https://www.googleapis.com/auth/spreadsheets",
        "access_type": "offline",
        "prompt": "consent",
        "state": state_b64,
    }
    return "https://accounts.google.com/o/oauth2/v2/auth?" + urllib.parse.urlencode(params)


def exchange_sheets_code(code: str, redirect_uri: str, account_id: int) -> Optional[Dict[str, Any]]:
    account = _get_account(account_id)
    oauth_cfg = _account_oauth(account)
    client_id = _require(oauth_cfg, "google_client_id")
    client_secret = _require(oauth_cfg, "google_client_secret")
    data = urllib.parse.urlencode({
        "code": code,
        "client_id": client_id,
        "client_secret": client_secret,
        "redirect_uri": redirect_uri,
        "grant_type": "authorization_code",
    }).encode()
    req = urllib.request.Request(
        "https://oauth2.googleapis.com/token",
        data=data,
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req) as resp:
            return json.loads(resp.read().decode())
    except urllib.error.HTTPError as e:
        try:
            body = e.read().decode()
        except Exception:
            body = "<unreadable>"
        logger.error(f"[OAuth] Google Sheets token exchange HTTP {e.code}: {body}")
        return None
    except Exception as e:
        logger.error(f"[OAuth] Google Sheets token exchange failed: {e}")
        return None


# ---------------------------------------------------------------------------
# Meta Marketing API OAuth
# ---------------------------------------------------------------------------

def get_meta_auth_url(account_id: int) -> str:
    account = _get_account(account_id)
    oauth_cfg = _account_oauth(account)
    app_id = _require(oauth_cfg, "meta_app_id")
    base = _redirect_base(oauth_cfg)
    redirect_uri = f"{base}/api/oauth/meta/callback"
    state_json = json.dumps({"account_id": account_id, "platform": "meta", "token": secrets.token_urlsafe(16)})
    from base64 import urlsafe_b64encode
    state = urlsafe_b64encode(state_json.encode()).decode().rstrip("=")
    params = {
        "client_id": app_id,
        "redirect_uri": redirect_uri,
        "scope": "ads_read,ads_management",
        "response_type": "code",
        "state": state,
    }
    return "https://www.facebook.com/v18.0/dialog/oauth?" + urllib.parse.urlencode(params)


def exchange_meta_code(code: str, redirect_uri: str, account_id: int) -> Optional[Dict[str, Any]]:
    account = _get_account(account_id)
    oauth_cfg = _account_oauth(account)
    app_id = _require(oauth_cfg, "meta_app_id")
    app_secret = _require(oauth_cfg, "meta_app_secret")
    params = {
        "client_id": app_id,
        "client_secret": app_secret,
        "redirect_uri": redirect_uri,
        "code": code,
    }
    url = "https://graph.facebook.com/v18.0/oauth/access_token?" + urllib.parse.urlencode(params)
    try:
        with urllib.request.urlopen(url) as resp:
            return json.loads(resp.read().decode())
    except Exception as e:
        logger.error(f"Meta token exchange failed: {e}")
        return None


def extend_meta_token(short_lived_token: str, account_id: int) -> Optional[str]:
    """Exchange short-lived user token for a 60-day long-lived token."""
    account = _get_account(account_id)
    oauth_cfg = _account_oauth(account)
    app_id = _require(oauth_cfg, "meta_app_id")
    app_secret = _require(oauth_cfg, "meta_app_secret")
    params = {
        "grant_type": "fb_exchange_token",
        "client_id": app_id,
        "client_secret": app_secret,
        "fb_exchange_token": short_lived_token,
    }
    url = "https://graph.facebook.com/v18.0/oauth/access_token?" + urllib.parse.urlencode(params)
    try:
        with urllib.request.urlopen(url) as resp:
            data = json.loads(resp.read().decode())
            return data.get("access_token", short_lived_token)
    except Exception as e:
        logger.error(f"Meta long-lived token exchange failed: {e}; using short-lived token")
        return short_lived_token


def build_meta_credentials(token_data: Dict[str, Any], account_id: int) -> Optional[str]:
    access_token = token_data.get("access_token")
    if not access_token:
        return None
    # When a system user token is configured, don't try to extend it and don't
    # store it per-account. Per-account storage is kept for backward compatibility.
    if os.environ.get("META_SYSTEM_USER_TOKEN"):
        return None
    long_token = extend_meta_token(access_token, account_id)
    creds = {"access_token": long_token}
    return encrypt(json.dumps(creds))


# ---------------------------------------------------------------------------
# State helpers
# ---------------------------------------------------------------------------

def parse_state(state_b64: str) -> Optional[Dict[str, Any]]:
    from base64 import urlsafe_b64decode
    try:
        # Add padding back
        pad = "=" * (-len(state_b64) % 4)
        raw = urlsafe_b64decode(state_b64 + pad)
        return json.loads(raw.decode())
    except Exception as e:
        logger.error(f"Failed to decode OAuth state: {e}")
        return None
