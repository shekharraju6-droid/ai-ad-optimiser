"""
Real notification dispatchers (Twilio WhatsApp + SMTP email) and logging.
"""
import os
import logging
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from typing import List, Dict, Any
from sqlalchemy.orm import Session
from backend.db.database import SessionLocal
from backend.db.models import NotificationSetting, NotificationLog

logger = logging.getLogger("AdOptima")


def _log(db: Session, channel: str, event_type: str, recipients: List[str], subject: str, body: str,
         status: str, provider_response: str = None, error_message: str = None) -> NotificationLog:
    log = NotificationLog(
        channel=channel,
        event_type=event_type,
        recipients=recipients,
        subject=subject,
        body=body,
        status=status,
        provider_response=provider_response,
        error_message=error_message,
    )
    db.add(log)
    db.commit()
    db.refresh(log)
    return log


def send_email(setting: NotificationSetting, event_type: str, subject: str, body: str,
               db: Session = None) -> Dict[str, Any]:
    close_session = False
    if db is None:
        db = SessionLocal()
        close_session = True

    recipients = (setting.config or {}).get("recipients", [])
    if not recipients:
        return _log(db, "email", event_type, recipients, subject, body, "failed",
                    error_message="No recipients configured").to_dict()

    smtp_host = (setting.config or {}).get("smtp_host") or os.getenv("SMTP_HOST", "smtp.gmail.com")
    smtp_port = int((setting.config or {}).get("smtp_port") or os.getenv("SMTP_PORT", "587"))
    smtp_user = (setting.config or {}).get("smtp_user") or os.getenv("SMTP_USER")
    smtp_pass = (setting.config or {}).get("smtp_pass") or os.getenv("SMTP_PASS")
    sender = (setting.config or {}).get("sender") or smtp_user or "adoptima@example.com"

    if not smtp_user or not smtp_pass:
        return _log(db, "email", event_type, recipients, subject, body, "failed",
                    error_message="SMTP credentials not configured").to_dict()

    try:
        msg = MIMEMultipart()
        msg["From"] = sender
        msg["To"] = ", ".join(recipients)
        msg["Subject"] = subject
        msg.attach(MIMEText(body, "plain"))

        server = smtplib.SMTP(smtp_host, smtp_port)
        server.starttls()
        server.login(smtp_user, smtp_pass)
        server.sendmail(sender, recipients, msg.as_string())
        server.quit()

        return _log(db, "email", event_type, recipients, subject, body, "sent",
                    provider_response="SMTP OK").to_dict()
    except Exception as e:
        logger.exception("SMTP send failed")
        return _log(db, "email", event_type, recipients, subject, body, "failed",
                    error_message=str(e)).to_dict()
    finally:
        if close_session:
            db.close()


def send_whatsapp(setting: NotificationSetting, event_type: str, subject: str, body: str,
                  db: Session = None) -> Dict[str, Any]:
    close_session = False
    if db is None:
        db = SessionLocal()
        close_session = True

    recipients = (setting.config or {}).get("recipients", [])
    if not recipients:
        return _log(db, "whatsapp", event_type, recipients, subject, body, "failed",
                    error_message="No recipients configured").to_dict()

    account_sid = (setting.config or {}).get("account_sid") or os.getenv("TWILIO_ACCOUNT_SID")
    auth_token = (setting.config or {}).get("auth_token") or os.getenv("TWILIO_AUTH_TOKEN")
    from_number = (setting.config or {}).get("from_number") or os.getenv("TWILIO_WHATSAPP_FROM")

    if not account_sid or not auth_token or not from_number:
        return _log(db, "whatsapp", event_type, recipients, subject, body, "failed",
                    error_message="Twilio credentials not configured").to_dict()

    try:
        from twilio.rest import Client
        client = Client(account_sid, auth_token)
        sent_sids = []
        for to in recipients:
            message = client.messages.create(
                from_=f"whatsapp:{from_number}",
                body=f"*{subject}*\n\n{body}",
                to=f"whatsapp:{to}",
            )
            sent_sids.append(message.sid)
        return _log(db, "whatsapp", event_type, recipients, subject, body, "sent",
                    provider_response=str(sent_sids)).to_dict()
    except Exception as e:
        logger.exception("Twilio WhatsApp send failed")
        return _log(db, "whatsapp", event_type, recipients, subject, body, "failed",
                    error_message=str(e)).to_dict()
    finally:
        if close_session:
            db.close()


def dispatch_channel(setting: NotificationSetting, event_type: str, subject: str, body: str,
                     db: Session = None) -> Dict[str, Any]:
    if setting.channel == "email":
        return send_email(setting, event_type, subject, body, db)
    if setting.channel == "whatsapp":
        return send_whatsapp(setting, event_type, subject, body, db)
    return {"error": "Unknown channel", "channel": setting.channel}
