from typing import Iterable, List, Optional
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
import copy

from pydantic import EmailStr
from sendgrid import SendGridAPIClient
from sendgrid.helpers.mail import Mail, Email, To, Cc, Bcc, Content, Personalization
from tenacity import retry, retry_if_exception, wait_exponential_jitter, stop_after_attempt
from requests.exceptions import ConnectionError, Timeout
from pydantic_settings import BaseSettings
from .exceptions import EmailServiceError

# ========================
# Config
# ========================

class PluginConfig(BaseSettings):
    sendgrid_api_key: str
    sender_email: EmailStr

# =========================
# Retry Logic
# =========================

def is_retryable_sendgrid_error(exc: Exception) -> bool:
    """Determine if a SendGrid error is retryable."""
    if isinstance(exc, (ConnectionError, Timeout)):
        return True
    # Retry on 5xx server errors
    if hasattr(exc, "status_code") and 500 <= exc.status_code < 600:
        return True
    return False

# =========================
# Plugin
# =========================

_thread_local = threading.local()

class SendGridPlugin:
    """
    SendGrid plugin for sending emails using API key.
    """
    ConfigClass = PluginConfig

    def __init__(self, config: PluginConfig, test_credentials: bool = True):
        self.config = config
        self.sender_email = config.sender_email

        # Initialize thread-local client
        self._get_client()

        if test_credentials:
            self.test_connection()

    # =========================
    # Service Helper (Thread-safe)
    # =========================

    def _get_client(self) -> SendGridAPIClient:
        """Return a thread-local SendGrid client."""
        if not hasattr(_thread_local, "client"):
            _thread_local.client = SendGridAPIClient(self.config.sendgrid_api_key)
        return _thread_local.client

    # =========================
    # Public API
    # =========================

    def test_connection(self) -> None:
        """Test if SendGrid API key is valid by sending a minimal request."""
        try:
            client = self._get_client()
            # SendGrid has a 'user/profile' endpoint for verification
            client.client.user.profile.get()
        except Exception as exc:
            raise EmailServiceError("SendGrid API credentials invalid") from exc

    def send_email(
        self,
        to_email: EmailStr,
        subject: str,
        content: str,
        html: bool = False,
        cc: Optional[Iterable[EmailStr]] = None,
        bcc: Optional[Iterable[EmailStr]] = None,
    ) -> None:
        message = self._build_message(
            to_email=to_email,
            subject=subject,
            content=content,
            html=html,
            cc=cc,
            bcc=bcc,
        )

        try:
            self._send_message(message)
        except Exception as exc:
            raise EmailServiceError(
                f"SendGrid send_email failed for {to_email}: {str(exc)}"
            ) from exc

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

        # Pre-build base message for performance
        base_message = Mail(
            from_email=str(self.sender_email),
            subject=subject,
            html_content=content if html else None,
            plain_text_content=content if not html else None,
        )
        if cc:
            base_message.add_ccs([Cc(str(c)) for c in cc])
        if bcc:
            base_message.add_bccs([Bcc(str(b)) for b in bcc])

        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            futures = {
                executor.submit(
                    self._send_individual_message,
                    recipient,
                    copy.deepcopy(base_message),
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
            raise EmailServiceError(
                f"{len(errors)} emails failed", details=details
            )

    # =========================
    # Internal Helpers
    # =========================

    def _send_individual_message(self, to_email: EmailStr, base_message: Mail):
        """Set recipient and send a single message."""
        personalization = Personalization()
        personalization.add_to(To(str(to_email)))

        # Preserve CC/BCC from base_message
        if base_message.ccs:
            for cc in base_message.ccs:
                personalization.add_cc(cc)
        if base_message.bccs:
            for bcc in base_message.bccs:
                personalization.add_bcc(bcc)

        base_message.add_personalization(personalization)
        self._send_message(base_message)

    @retry(
        retry=retry_if_exception(is_retryable_sendgrid_error),
        wait=wait_exponential_jitter(initial=1, max=30),
        stop=stop_after_attempt(5),
        reraise=True,
    )
    def _send_message(self, message: Mail) -> None:
        client = self._get_client()
        response = client.send(message)
        if response.status_code >= 400:
            raise EmailServiceError(f"SendGrid API error {response.status_code}: {response.body}")

    def _build_message(
        self,
        to_email: EmailStr,
        subject: str,
        content: str,
        html: bool = False,
        cc: Optional[Iterable[EmailStr]] = None,
        bcc: Optional[Iterable[EmailStr]] = None,
    ) -> Mail:
        """Build a SendGrid Mail object."""
        message = Mail(
            from_email=str(self.sender_email),
            subject=subject,
            html_content=content if html else None,
            plain_text_content=content if not html else None,
        )

        personalization = Personalization()
        personalization.add_to(To(str(to_email)))

        if cc:
            for c in cc:
                personalization.add_cc(Cc(str(c)))
        if bcc:
            for b in bcc:
                personalization.add_bcc(Bcc(str(b)))

        message.add_personalization(personalization)
        return message
