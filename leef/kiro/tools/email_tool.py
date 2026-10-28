from __future__ import annotations
"""Email tool — send emails via Gmail SMTP (or any SMTP server)."""

import os
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

from .base import BaseTool


class SendEmailTool(BaseTool):
    name = "send_email"
    description = (
        "Send an email via Gmail (or any SMTP server). "
        "Requires GMAIL_ADDRESS and GMAIL_APP_PASSWORD environment variables, "
        "or pass them directly. Use Gmail App Passwords — not your regular password. "
        "Get one at: https://myaccount.google.com/apppasswords"
    )
    parameters = {
        "type": "object",
        "properties": {
            "to": {
                "type": "string",
                "description": "Recipient email address (or comma-separated list).",
            },
            "subject": {
                "type": "string",
                "description": "Email subject line.",
            },
            "body": {
                "type": "string",
                "description": "Email body — plain text or HTML.",
            },
            "cc": {
                "type": "string",
                "description": "CC email address(es), comma-separated. Optional.",
            },
            "html": {
                "type": "boolean",
                "description": "If true, body is treated as HTML. Default false.",
            },
        },
        "required": ["to", "subject", "body"],
    }

    def __init__(
        self,
        gmail_address: str | None = None,
        app_password: str | None = None,
        smtp_host: str = "smtp.gmail.com",
        smtp_port: int = 587,
    ):
        self.gmail_address = gmail_address or os.environ.get("GMAIL_ADDRESS", "")
        self.app_password = app_password or os.environ.get("GMAIL_APP_PASSWORD", "")
        self.smtp_host = smtp_host
        self.smtp_port = smtp_port

    def execute(
        self,
        to: str,
        subject: str,
        body: str,
        cc: str | None = None,
        html: bool = False,
    ) -> str:
        if not self.gmail_address:
            return (
                "Error: No Gmail address configured. "
                "Set GMAIL_ADDRESS environment variable or pass gmail_address to SendEmailTool()."
            )
        if not self.app_password:
            return (
                "Error: No Gmail app password configured. "
                "Set GMAIL_APP_PASSWORD environment variable. "
                "Create one at: https://myaccount.google.com/apppasswords"
            )

        try:
            msg = MIMEMultipart("alternative")
            msg["From"] = self.gmail_address
            msg["To"] = to
            msg["Subject"] = subject
            if cc:
                msg["Cc"] = cc

            mime_type = "html" if html else "plain"
            msg.attach(MIMEText(body, mime_type))

            recipients = [r.strip() for r in to.split(",")]
            if cc:
                recipients += [r.strip() for r in cc.split(",")]

            with smtplib.SMTP(self.smtp_host, self.smtp_port) as server:
                server.ehlo()
                server.starttls()
                server.login(self.gmail_address, self.app_password)
                server.sendmail(self.gmail_address, recipients, msg.as_string())

            return f"Email sent successfully to {to} — subject: {subject!r}"

        except smtplib.SMTPAuthenticationError:
            return (
                "Error: Gmail authentication failed. "
                "Make sure you're using an App Password, not your regular Gmail password. "
                "Create one at: https://myaccount.google.com/apppasswords"
            )
        except smtplib.SMTPException as e:
            return f"Error sending email: {e}"
        except Exception as e:
            return f"Error: {type(e).__name__}: {e}"
