# email_services/plugins/customSMTP/plugin.py

import smtplib
import threading
import copy
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from typing import Iterable, Optional
from concurrent.futures import ThreadPoolExecutor, as_completed
from tenacity import retry, retry_if_exception, wait_exponential_jitter, stop_after_attempt
from pydantic import EmailStr
from pydantic_settings import BaseSettings
from .exceptions import EmailServiceError

# ========================
# Config
# ========================

class PluginConfig(BaseSettings):
    smtp_host: str
    smtp_port: int = 587
    smtp_username: Optional[str] = None
    smtp_password: Optional[str] = None
    use_tls: bool = True
    sender_email: EmailStr

# =========================
# Retry Logic
# =========================

def is_retryable_smtp_error(exc: Exception) -> bool:
    """Determine if an SMTP error is retryable."""
    return isinstance(exc, (smtplib.SMTPServerDisconnected, smtplib.SMTPConnectError,
                            smtplib.SMTPRecipientsRefused, smtplib.SMTPDataError))

# =========================
# Thread-local SMTP
# =========================

_thread_local = threading.local()

def _get_smtp_client(config: PluginConfig) -> smtplib.SMTP:
    """Return thread-local SMTP client (initialize if not exists)."""
    if not hasattr(_thread_local, "smtp_client"):
        client = smtplib.SMTP(config.smtp_host, config.smtp_port, timeout=30)
        try:
            if config.use_tls:
                client.starttls()
            if config.smtp_username and config.smtp_password:
                client.login(config.smtp_username, config.smtp_password)
        except smtplib.SMTPException as exc:
            # Fail gracefully here, plugin manager can still load plugin
            raise EmailServiceError(f"SMTP connection setup failed: {exc}") from exc
        _thread_local.smtp_client = client
    return _thread_local.smtp_client

# =========================
# Plugin
# =========================

class CustomSMTPPlugin:
    """
    Custom SMTP email plugin supporting single and bulk sending, HTML/plain text, CC/BCC, and retries.
    """
    ConfigClass = PluginConfig

    def __init__(self, config: PluginConfig, test_connection: bool = True):
        self.config = config
        self.sender_email = config.sender_email

        # Initialize thread-local SMTP client
        try:
            _get_smtp_client(self.config)
        except EmailServiceError as exc:
            if test_connection:
                raise  # Only raise if testing connection immediately
            else:
                # Log or ignore; plugin still loads
                print(f"Warning: SMTP client not fully initialized: {exc}")

        if test_connection:
            try:
                self.test_connection()
            except EmailServiceError as exc:
                # Fail gracefully, but provide info
                raise EmailServiceError(f"SMTP test connection failed: {exc}") from exc

    # =========================
    # Public API
    # =========================

    def test_connection(self) -> None:
        """Test if SMTP connection works."""
        try:
            client = _get_smtp_client(self.config)
            client.noop()
        except Exception as exc:
            raise EmailServiceError("SMTP connection test failed") from exc

    def send_email(
        self,
        to_email: EmailStr,
        subject: str,
        content: str,
        html: bool = False,
        cc: Optional[Iterable[EmailStr]] = None,
        bcc: Optional[Iterable[EmailStr]] = None,
    ) -> None:
        msg = self._build_message(to_email, subject, content, html, cc, bcc)
        try:
            self._send_message(msg, [to_email] + list(cc or []) + list(bcc or []))
        except Exception as exc:
            raise EmailServiceError(f"send_email failed for {to_email}: {exc}") from exc

    def send_bulk_email(
        self,
        recipients: Iterable[EmailStr],
        subject: str,
        content: str,
        html: bool = False,
        cc: Optional[Iterable[EmailStr]] = None,
        bcc: Optional[Iterable[EmailStr]] = None,
        max_workers: int = 5,
    ) -> None:
        recipient_list = list(recipients)
        errors = []

        base_msg = self._build_message("placeholder", subject, content, html, cc, bcc)

        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            futures = {
                executor.submit(
                    self._send_individual_message,
                    recipient,
                    copy.deepcopy(base_msg),
                    cc,
                    bcc,
                ): recipient
                for recipient in recipient_list
            }

            for future in as_completed(futures):
                recipient = futures[future]
                try:
                    future.result()
                except Exception as exc:
                    errors.append((recipient, exc))

        if errors:
            details = {str(r): str(e) for r, e in errors}
            raise EmailServiceError(f"{len(errors)} emails failed", details=details)

    # =========================
    # Internal Helpers
    # =========================

    def _send_individual_message(self, to_email: EmailStr, msg: MIMEMultipart,
                                 cc: Optional[Iterable[EmailStr]], bcc: Optional[Iterable[EmailStr]]):
        msg["To"] = str(to_email)
        if cc:
            msg["Cc"] = ", ".join(map(str, cc))
        recipients = [to_email] + list(cc or []) + list(bcc or [])
        self._send_message(msg, recipients)

    @retry(
        retry=retry_if_exception(is_retryable_smtp_error),
        wait=wait_exponential_jitter(initial=1, max=30),
        stop=stop_after_attempt(5),
        reraise=True,
    )
    def _send_message(self, msg: MIMEMultipart, recipients: list[str]) -> None:
        client = _get_smtp_client(self.config)
        client.sendmail(self.sender_email, recipients, msg.as_string())

    def _build_message(
        self,
        to_email: EmailStr,
        subject: str,
        content: str,
        html: bool = False,
        cc: Optional[Iterable[EmailStr]] = None,
        bcc: Optional[Iterable[EmailStr]] = None,
    ) -> MIMEMultipart:
        msg = MIMEMultipart()
        msg["From"] = str(self.sender_email)
        msg["To"] = str(to_email)
        msg["Subject"] = subject
        if cc:
            msg["Cc"] = ", ".join(map(str, cc))

        mime_content = MIMEText(content, "html" if html else "plain")
        msg.attach(mime_content)
        return msg
        client.sendmail(self.sender_email, recipients, msg.as_string())

    def _build_message(
        self,
        to_email: EmailStr,
        subject: str,
        content: str,
        html: bool = False,
        cc: Optional[Iterable[EmailStr]] = None,
        bcc: Optional[Iterable[EmailStr]] = None,
    ) -> MIMEMultipart:
        msg = MIMEMultipart()
        msg["From"] = str(self.sender_email)
        msg["To"] = str(to_email)
        msg["Subject"] = subject
        if cc:
            msg["Cc"] = ", ".join(map(str, cc))

        mime_content = MIMEText(content, "html" if html else "plain")
        msg.attach(mime_content)
        return msg
