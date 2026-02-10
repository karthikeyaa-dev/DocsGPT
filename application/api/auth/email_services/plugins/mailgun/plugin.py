# email_services/plugins/mailgun/plugin.py
import copy
from typing import Iterable, Optional
from concurrent.futures import ThreadPoolExecutor, as_completed
from pydantic import EmailStr
from pydantic_settings import BaseSettings
from tenacity import retry, retry_if_exception, wait_exponential_jitter, stop_after_attempt
import requests
from .exceptions import EmailServiceError

# ========================
# Config
# ========================

class PluginConfig(BaseSettings):
    api_key: str
    domain: str
    sender_email: EmailStr
    base_url: str = "https://api.mailgun.net/v3"

# =========================
# Retry Logic
# =========================

def is_retryable_mailgun_error(exc: Exception) -> bool:
    """Determine if a Mailgun error is retryable."""
    return isinstance(exc, EmailServiceError) and getattr(exc, "retryable", False)

# =========================
# Plugin
# =========================

class MailgunPlugin:
    """
    Mailgun plugin supporting single/bulk sending, HTML/plain text, CC/BCC, retries.
    """
    ConfigClass = PluginConfig

    def __init__(self, config: PluginConfig, test_connection: bool = True):
        self.config = config
        self.sender_email = config.sender_email

        if test_connection:
            self.test_connection()

    # =========================
    # Public API
    # =========================

    def test_connection(self) -> None:
        """Test Mailgun API credentials by fetching stats."""
        url = f"{self.config.base_url}/{self.config.domain}/stats/total"
        try:
            r = requests.get(
                url,
                auth=("api", self.config.api_key),
                params={"event": "accepted", "duration": "1h"}
            )
            if r.status_code == 401:
                raise EmailServiceError("Mailgun API credentials invalid")
            r.raise_for_status()
        except requests.RequestException as exc:
            raise EmailServiceError(f"Mailgun test connection failed: {exc}") from exc

    def send_email(
        self,
        to_email: EmailStr,
        subject: str,
        content: str,
        html: bool = False,
        cc: Optional[Iterable[EmailStr]] = None,
        bcc: Optional[Iterable[EmailStr]] = None,
    ) -> None:
        payload = self._build_message(to_email, subject, content, html, cc, bcc)
        try:
            self._send_message(payload)
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
                    copy.deepcopy(base_msg)
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

    def _send_individual_message(self, to_email: EmailStr, msg: dict):
        msg["to"] = str(to_email)
        self._send_message(msg)

    @retry(
        retry=retry_if_exception(is_retryable_mailgun_error),
        wait=wait_exponential_jitter(initial=1, max=30),
        stop=stop_after_attempt(5),
        reraise=True,
    )
    def _send_message(self, msg: dict) -> None:
        url = f"{self.config.base_url}/{self.config.domain}/messages"
        try:
            r = requests.post(url, auth=("api", self.config.api_key), data=msg)
            if r.status_code >= 500:
                exc = EmailServiceError(f"Mailgun server error: {r.status_code}")
                exc.retryable = True
                raise exc
            elif r.status_code >= 400:
                raise EmailServiceError(f"Mailgun client error: {r.status_code} {r.text}")
        except requests.RequestException as exc:
            raise EmailServiceError(f"Mailgun request failed: {exc}") from exc

    def _build_message(
        self,
        to_email: str,
        subject: str,
        content: str,
        html: bool = False,
        cc: Optional[Iterable[EmailStr]] = None,
        bcc: Optional[Iterable[EmailStr]] = None,
    ) -> dict:
        payload = {
            "from": str(self.sender_email),
            "to": str(to_email),
            "subject": subject,
            "text": content if not html else None,
            "html": content if html else None,
        }
        if cc:
            payload["cc"] = ", ".join(map(str, cc))
        if bcc:
            payload["bcc"] = ", ".join(map(str, bcc))
        return payload
