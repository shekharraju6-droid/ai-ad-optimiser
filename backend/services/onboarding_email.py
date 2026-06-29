"""
Onboarding invitation email sender (Outlook / Office 365 SMTP).
"""
import os
import logging
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from typing import Dict, Any

logger = logging.getLogger("AdOptima")


def send_onboarding_email(recipient_email: str, full_name: str, setup_link: str) -> Dict[str, Any]:
    """Send a setup-link email to a newly created user via SMTP."""
    smtp_host = os.getenv("SMTP_HOST", "smtp.office365.com")
    smtp_port = int(os.getenv("SMTP_PORT", "587"))
    smtp_user = os.getenv("SMTP_USER", "")
    smtp_pass = os.getenv("SMTP_PASS", "")
    sender_name = os.getenv("SMTP_SENDER_NAME", "ChlearSakhaaOps AI")

    if not smtp_user or not smtp_pass:
        return {
            "sent": False,
            "error": "SMTP credentials not configured. Add SMTP_USER and SMTP_PASS to Railway variables.",
        }

    sender = smtp_user
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

    try:
        msg = MIMEMultipart("alternative")
        msg["From"] = f"{sender_name} <{sender}>"
        msg["To"] = recipient_email
        msg["Subject"] = subject
        msg.attach(MIMEText(plain_body, "plain"))
        msg.attach(MIMEText(html_body, "html"))

        server = smtplib.SMTP(smtp_host, smtp_port)
        server.starttls()
        server.login(smtp_user, smtp_pass)
        server.sendmail(sender, [recipient_email], msg.as_string())
        server.quit()

        logger.info(f"Onboarding email sent to {recipient_email}")
        return {"sent": True, "error": None}
    except Exception as e:
        logger.exception(f"Failed to send onboarding email to {recipient_email}: {e}")
        return {"sent": False, "error": str(e)}
