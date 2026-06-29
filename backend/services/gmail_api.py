"""
Gmail API email sender.

Uses OAuth2 refresh token to send emails via the Gmail REST API (HTTPS).
This bypasses SMTP port blocking / timeouts on cloud hosts like Railway.
"""
import os
import base64
import logging
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.utils import formataddr
from typing import Dict, Any, Optional

from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import Flow
from googleapiclient.discovery import build
from google.auth.transport.requests import Request

logger = logging.getLogger("AdOptima")


def _get_oauth_config() -> Dict[str, Any]:
    """Return Gmail OAuth client config from environment."""
    client_id = os.getenv("GMAIL_CLIENT_ID", "").strip()
    client_secret = os.getenv("GMAIL_CLIENT_SECRET", "").strip()
    redirect_uri = os.getenv("GMAIL_REDIRECT_URI", "").strip()
    if not client_id or not client_secret:
        return {"error": "GMAIL_CLIENT_ID and GMAIL_CLIENT_SECRET must be set"}
    if not redirect_uri:
        return {"error": "GMAIL_REDIRECT_URI must be set"}
    return {
        "installed": {
            "client_id": client_id,
            "client_secret": client_secret,
            "auth_uri": "https://accounts.google.com/o/oauth2/auth",
            "token_uri": "https://oauth2.googleapis.com/token",
            "redirect_uris": [redirect_uri],
        }
    }


def _scopes() -> list:
    return ["https://www.googleapis.com/auth/gmail.send"]


def build_authorization_url(redirect_uri: Optional[str] = None) -> Dict[str, Any]:
    """Build the Google OAuth URL for the admin to authorize Gmail sending."""
    cfg = _get_oauth_config()
    if cfg.get("error"):
        return cfg
    if redirect_uri:
        cfg["installed"]["redirect_uris"] = [redirect_uri]
    try:
        flow = Flow.from_client_config(cfg, scopes=_scopes())
        flow.redirect_uri = cfg["installed"]["redirect_uris"][0]
        url, state = flow.authorization_url(
            access_type="offline",
            include_granted_scopes="true",
            prompt="consent",
        )
        return {"url": url, "state": state}
    except Exception as e:
        logger.exception(f"Failed to build Gmail authorization URL: {e}")
        return {"error": str(e)}


def exchange_code_for_token(code: str, redirect_uri: Optional[str] = None) -> Dict[str, Any]:
    """Exchange OAuth authorization code for refresh token."""
    cfg = _get_oauth_config()
    if cfg.get("error"):
        return cfg
    if redirect_uri:
        cfg["installed"]["redirect_uris"] = [redirect_uri]
    try:
        flow = Flow.from_client_config(cfg, scopes=_scopes())
        flow.redirect_uri = cfg["installed"]["redirect_uris"][0]
        flow.fetch_token(code=code)
        creds = flow.credentials
        return {
            "refresh_token": creds.refresh_token,
            "token": creds.token,
            "expiry": creds.expiry.isoformat() if creds.expiry else None,
        }
    except Exception as e:
        logger.exception(f"Failed to exchange Gmail OAuth code: {e}")
        return {"error": str(e)}


def _get_credentials_from_refresh_token(refresh_token: str) -> Optional[Credentials]:
    client_id = os.getenv("GMAIL_CLIENT_ID", "").strip()
    client_secret = os.getenv("GMAIL_CLIENT_SECRET", "").strip()
    if not client_id or not client_secret or not refresh_token:
        return None
    try:
        creds = Credentials(
            token=None,
            refresh_token=refresh_token,
            token_uri="https://oauth2.googleapis.com/token",
            client_id=client_id,
            client_secret=client_secret,
            scopes=_scopes(),
        )
        creds.refresh(Request())
        return creds
    except Exception as e:
        logger.error(f"Failed to refresh Gmail credentials: {e}")
        return None


def send_email_via_gmail_api(
    recipient_email: str,
    subject: str,
    plain_body: str,
    html_body: str,
    sender_email: str,
    sender_name: str,
    refresh_token: str,
) -> Dict[str, Any]:
    """Send an email using the Gmail API."""
    creds = _get_credentials_from_refresh_token(refresh_token)
    if not creds:
        return {"sent": False, "error": "Gmail credentials not available or refresh failed"}

    msg = MIMEMultipart("alternative")
    msg["From"] = formataddr((sender_name, sender_email))
    msg["To"] = recipient_email
    msg["Subject"] = subject
    msg.attach(MIMEText(plain_body, "plain", _charset="utf-8"))
    msg.attach(MIMEText(html_body, "html", _charset="utf-8"))

    raw = base64.urlsafe_b64encode(msg.as_bytes()).decode("utf-8")

    try:
        service = build("gmail", "v1", credentials=creds, cache_discovery=False)
        result = service.users().messages().send(userId="me", body={"raw": raw}).execute()
        message_id = result.get("id")
        logger.info(f"Gmail API sent email to {recipient_email}, message_id={message_id}")
        return {"sent": True, "error": None, "provider": "gmail_api", "message_id": message_id}
    except Exception as e:
        logger.exception(f"Gmail API send failed for {recipient_email}: {e}")
        return {"sent": False, "error": str(e), "provider": "gmail_api"}
