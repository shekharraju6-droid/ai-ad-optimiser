"""
Onboarding invitation email sender.

Priority:
  1. SendGrid API (HTTPS, works from Railway, no domain verification needed for free tier)
  2. SMTP fallback (may be blocked on Railway / cloud hosts)

Environment variables:
  SENDGRID_API_KEY       -> SendGrid API key
  SENDGRID_FROM          -> sender address (any address works on free tier)
  SMTP_HOST, SMTP_PORT, SMTP_USER, SMTP_PASS -> legacy SMTP fallback
"""
import os
import json
import logging
import smtplib
import time
from datetime import datetime
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.utils import formataddr, make_msgid
from typing import Dict, Any

import urllib.request
import urllib.error

logger = logging.getLogger("AdOptima")


def _smtp_from_env() -> Dict[str, Any]:
    """Read SMTP settings from environment with sane defaults and validation."""
    smtp_host = os.getenv("SMTP_HOST", "smtp.gmail.com").strip()
    smtp_port_raw = os.getenv("SMTP_PORT", "587").strip()
    smtp_user = os.getenv("SMTP_USER", "").strip()
    smtp_pass = os.getenv("SMTP_PASS", "").strip()
    smtp_from = os.getenv("SMTP_FROM", smtp_user).strip()
    sender_name = os.getenv("SMTP_SENDER_NAME", "ChlearSakhaaOps AI").strip()

    try:
        smtp_port = int(smtp_port_raw)
    except ValueError:
        return {"error": f"Invalid SMTP_PORT value: {smtp_port_raw!r}"}

    if not smtp_host or not smtp_port:
        return {"error": "SMTP_HOST/SMTP_PORT not configured"}
    if not smtp_user or not smtp_pass:
        return {
            "error": "SMTP_USER and SMTP_PASS are required for SMTP fallback.",
        }

    return {
        "host": smtp_host,
        "port": smtp_port,
        "user": smtp_user,
        "pass": smtp_pass,
        "from": smtp_from or smtp_user,
        "sender_name": sender_name or "ChlearSakhaaOps AI",
    }


def _build_email_payloads(recipient_email: str, full_name: str, setup_link: str, sender_name: str) -> Dict[str, str]:
    subject = "Welcome to ChlearSakhaaOps AI - Set up your account"
    html_body = f"""
    <html>
    <body style="font-family: Arial, sans-serif; line-height: 1.6; color: #333;">
        <p>Hi {full_name or 'there'},</p>
        <p>You have been invited to access <strong>ChlearSakhaaOps AI</strong>.</p>
        <p>Click the button below to set your password and activate your account:</p>
        <p>
            <a href="{setup_link}" style="display:inline-block;padding:12px 24px;background:#2563eb;color:#fff;text-decoration:none;border-radius:6px;">
                Set up my account
            </a>
        </p>
        <p>Or copy and paste this link into your browser:</p>
        <p><a href="{setup_link}">{setup_link}</a></p>
        <p>This link expires in 72 hours.</p>
        <p>If you did not expect this invitation, please ignore this email.</p>
        <br>
        <p>Best regards,<br>{sender_name}</p>
    </body>
    </html>
    """

    plain_body = f"""Hi {full_name or 'there'},

You have been invited to access ChlearSakhaaOps AI.

Click the link below to set your password and activate your account:
{setup_link}

This link expires in 72 hours.

Best regards,
{sender_name}
"""
    return {"subject": subject, "html": html_body, "text": plain_body}


def _http_post(url: str, payload: Dict[str, Any], headers: Dict[str, str], timeout: int = 30) -> Dict[str, Any]:
    """Minimal dependency-free JSON HTTP POST using only stdlib."""
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=data,
        headers={"Content-Type": "application/json", **headers},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            body = resp.read().decode("utf-8")
            return {"status": resp.status, "body": body}
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8")
        return {"status": e.code, "body": body, "error": f"HTTP {e.code}: {body[:500]}"}
    except Exception as e:
        return {"error": str(e)}


def _send_via_sendgrid(
    recipient_email: str, full_name: str, setup_link: str, api_key: str, sender: str, sender_name: str
) -> Dict[str, Any]:
    logger.info(f"Sending onboarding email via SendGrid API to {recipient_email} from {sender}")
    payloads = _build_email_payloads(recipient_email, full_name, setup_link, sender_name)
    payload = {
        "personalizations": [{"to": [{"email": recipient_email, "name": full_name or recipient_email}]}],
        "from": {"email": sender, "name": sender_name},
        "subject": payloads["subject"],
        "content": [
            {"type": "text/plain", "value": payloads["text"]},
            {"type": "text/html", "value": payloads["html"]},
        ],
    }
    result = _http_post(
        "https://api.sendgrid.com/v3/mail/send",
        payload,
        {"Authorization": f"Bearer {api_key}"},
        timeout=30,
    )
    if result.get("error"):
        err = f"SendGrid API error: {result['error']}"
        logger.error(err)
        return {"sent": False, "error": err}
    status = result.get("status", 0)
    if status in (200, 201, 202):
        logger.info(f"SendGrid accepted email for {recipient_email}")
        return {"sent": True, "error": None, "provider": "sendgrid"}
    body = result.get("body", "")
    err = f"SendGrid API returned {status}: {body[:500]}"
    logger.error(err)
    return {"sent": False, "error": err}


def _send_via_smtp(
    recipient_email: str, full_name: str, setup_link: str, timeout: int = 30
) -> Dict[str, Any]:
    cfg = _smtp_from_env()
    if cfg.get("error"):
        logger.error(f"SMTP fallback misconfiguration: {cfg['error']}")
        return {"sent": False, "error": cfg["error"], "provider": "smtp"}

    sender_email = cfg["from"]
    sender_name = cfg["sender_name"]
    payloads = _build_email_payloads(recipient_email, full_name, setup_link, sender_name)
    message_id = make_msgid(domain=sender_email.split("@")[-1] or "adoptima.ai")

    msg = MIMEMultipart("alternative")
    msg["From"] = formataddr((sender_name, sender_email))
    msg["To"] = recipient_email
    msg["Subject"] = payloads["subject"]
    msg["Message-ID"] = message_id
    msg["Date"] = datetime.utcnow().strftime("%a, %d %b %Y %H:%M:%S +0000")
    msg["Reply-To"] = sender_email
    msg["X-Mailer"] = "AdOptimaMailer/1.0"
    msg["Precedence"] = "bulk"
    msg["Auto-Submitted"] = "auto-generated"
    msg.attach(MIMEText(payloads["text"], "plain", _charset="utf-8"))
    msg.attach(MIMEText(payloads["html"], "html", _charset="utf-8"))

    try:
        logger.info(
            f"Connecting to SMTP {cfg['host']}:{cfg['port']} as {cfg['user']} "
            f"to send onboarding email to {recipient_email} (msgid={message_id})"
        )
        start = time.time()
        server = smtplib.SMTP(cfg["host"], cfg["port"], timeout=timeout)
        server.ehlo()
        server.starttls()
        server.ehlo()
        server.login(cfg["user"], cfg["pass"])
        response = server.sendmail(sender_email, [recipient_email], msg.as_string())
        server.quit()
        elapsed = round(time.time() - start, 2)

        if response:
            logger.error(f"SMTP server rejected recipients for {recipient_email}: {response}")
            return {
                "sent": False,
                "error": f"SMTP server rejected recipients: {response}",
                "provider": "smtp",
                "smtp_host": cfg["host"],
                "smtp_from": sender_email,
                "message_id": message_id,
            }

        logger.info(f"Onboarding email ACCEPTED by SMTP for {recipient_email} in {elapsed}s (msgid={message_id})")
        return {
            "sent": True,
            "error": None,
            "provider": "smtp",
            "smtp_host": cfg["host"],
            "smtp_from": sender_email,
            "message_id": message_id,
        }
    except smtplib.SMTPAuthenticationError as e:
        err = f"SMTP authentication failed for {cfg['user']}: {e.smtp_error}"
        logger.exception(err)
        return {"sent": False, "error": err, "provider": "smtp"}
    except smtplib.SMTPRecipientsRefused as e:
        err = f"SMTP server refused recipient {recipient_email}: {e.recipients}"
        logger.exception(err)
        return {"sent": False, "error": err, "provider": "smtp"}
    except smtplib.SMTPException as e:
        err = f"SMTP error while sending to {recipient_email}: {e}"
        logger.exception(err)
        return {"sent": False, "error": err, "provider": "smtp"}
    except Exception as e:
        err = f"Unexpected error sending onboarding email to {recipient_email}: {e}"
        logger.exception(err)
        return {"sent": False, "error": err, "provider": "smtp"}


def send_onboarding_email(
    recipient_email: str,
    full_name: str,
    setup_link: str,
    timeout: int = 30,
) -> Dict[str, Any]:
    """
    Send a setup-link email to a newly created user.

    Uses SendGrid HTTPS API first (works from Railway/cloud without domain verification),
    falls back to SMTP only if no API key is configured.

    Returns a dict with keys:
      - sent: bool
      - error: str | None
      - provider: str (sendgrid|smtp)
      - message_id, smtp_host, smtp_from for debugging
    """
    sender_name = os.getenv("SMTP_SENDER_NAME", "ChlearSakhaaOps AI").strip()

    sendgrid_key = os.getenv("SENDGRID_API_KEY", "").strip()
    sendgrid_from = os.getenv("SENDGRID_FROM", os.getenv("SMTP_FROM", os.getenv("SMTP_USER", ""))).strip()
    if sendgrid_key and sendgrid_from:
        return _send_via_sendgrid(recipient_email, full_name, setup_link, sendgrid_key, sendgrid_from, sender_name)

    logger.warning("No SendGrid API key found; falling back to SMTP (may fail on Railway)")
    return _send_via_smtp(recipient_email, full_name, setup_link, timeout=timeout)
