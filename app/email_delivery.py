"""SMTP verification delivery. No console/outbox fallback for patient secrets."""
from email.message import EmailMessage
from functools import lru_cache
import os
import smtplib
import ssl

from services.verification import VerificationService


class SMTPCodeSender:
    def send(self, email: str, code: str) -> None:
        host, sender = os.getenv("VAST_SMTP_HOST", ""), os.getenv("VAST_SMTP_FROM", "")
        if not host or not sender:
            raise RuntimeError("SMTP delivery is not configured")
        message = EmailMessage()
        message["From"], message["To"] = sender, email
        message["Subject"] = "NextDim account verification"
        message.set_content(f"Your NextDim verification code is {code}. It expires in 10 minutes. Do not share it. If you did not request it, ignore this email.")
        with smtplib.SMTP(host, int(os.getenv("VAST_SMTP_PORT", "587")), timeout=15) as smtp:
            smtp.starttls(context=ssl.create_default_context())
            username = os.getenv("VAST_SMTP_USERNAME", "")
            if username:
                smtp.login(username, os.getenv("VAST_SMTP_PASSWORD", ""))
            smtp.send_message(message)


@lru_cache(maxsize=1)
def verification_service() -> VerificationService:
    return VerificationService(SMTPCodeSender())