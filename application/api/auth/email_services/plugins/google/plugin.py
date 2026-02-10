import base64
from email.mime.text import MIMEText
from typing import Iterable, List, Optional
from pydantic import EmailStr, FilePath
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from google.oauth2 import service_account
from pydantic_settings import BaseSettings
from concurrent.futures import ThreadPoolExecutor, as_completed
from .exceptions import EmailServiceError
from tenacity import (
    retry,
    retry_if_exception,
    wait_exponential_jitter,
    stop_after_attempt,
)
from requests.exceptions import ConnectionError, Timeout
import threading
import copy

# ========================
# Config
# ========================

class PluginConfig(BaseSettings):
    service_account_file: FilePath
    sender_email: EmailStr
    scopes: List[str] = ["https://www.googleapis.com/auth/gmail.send"]    

# =========================
# Retry Logic
# =========================

def is_retryable_gmail_error(exc: Exception) -> bool:
    """Determine if a Gmail API error is retryable."""
    if isinstance(exc, (ConnectionError, Timeout)):
        return True
    if isinstance(exc, HttpError):
        return exc.resp.status in {429, 500, 502, 503, 504}
    return False


# =========================
# Plugin
# =========================

_thread_local = threading.local()

class GoogleCloudGmailPlugin:
    """
    Google Cloud Gmail API plugin using Service Account.

    Requirements:
    - Google Workspace account
    - Domain-wide delegation for the service account
    """

    def __init__(self, config: PluginConfig, test_credentials: bool = True):
        self.config = config
        self.sender_email = config.sender_email

        # Initialize thread-local service
        self._get_service()

        # Optional immediate credential validation
        if test_credentials:
            self.test_connection()

    # =========================
    # Service Helper (Thread-safe)
    # =========================

    def _get_service(self):
        """Return a thread-local Gmail API service."""
        if not hasattr(_thread_local, "service"):
            credentials = service_account.Credentials.from_service_account_file(
                self.config.service_account_file,
                scopes=self.config.scopes,
            ).with_subject(self.sender_email)

            _thread_local.service = build(
                "gmail",
                "v1",
                credentials=credentials,
                cache_discovery=False,
            )
        return _thread_local.service

    # =========================
    # Public API
    # =========================

    def test_connection(self) -> None:
        """Test if Gmail API credentials are valid."""
        try:
            service = self._get_service()
            service.users().getProfile(userId=str(self.sender_email)).execute()
        except HttpError as exc:
            raise EmailServiceError(
                "Gmail API credentials invalid or expired"
            ) from exc

    def send_email(
        self,
        to_email: EmailStr,
        subject: str,
        content: str,
        html: bool = False,
        cc: Optional[Iterable[EmailStr]] = None,
        bcc: Optional[Iterable[EmailStr]] = None,
    ) -> None:
        raw_message = self._build_message(
            to_email=to_email,
            subject=subject,
            content=content,
            html=html,
            cc=cc,
            bcc=bcc,
        )

        try:
            self._send_raw_message(raw_message)
        except HttpError as exc:
            error_message = (
                exc.content.decode()
                if hasattr(exc, "content") and exc.content
                else str(exc)
            )
            raise EmailServiceError(
                f"Gmail API send_email failed for {to_email}: {error_message}"
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

        # Pre-build base MIME message for performance
        base_message = MIMEText(content, "html" if html else "plain")
        base_message["From"] = str(self.sender_email)
        base_message["Subject"] = subject
        if cc:
            base_message["Cc"] = ", ".join(map(str, cc))

        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            futures = {
                executor.submit(
                    self._send_individual_message,
                    recipient,
                    copy.deepcopy(base_message),
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
            raise EmailServiceError(
                f"{len(errors)} emails failed", details=details
            )

    # =========================
    # Internal Helpers
    # =========================

    def _send_individual_message(
        self,
        to_email: EmailStr,
        base_message: MIMEText,
        bcc: Optional[Iterable[EmailStr]] = None,
    ):
        """Set recipient and send a single message."""
        base_message["To"] = str(to_email)
        if bcc:
            base_message["Bcc"] = ", ".join(map(str, bcc))
        raw_message = base64.urlsafe_b64encode(base_message.as_bytes()).decode("utf-8")
        self._send_raw_message(raw_message)

    @retry(
        retry=retry_if_exception(is_retryable_gmail_error),
        wait=wait_exponential_jitter(initial=1, max=30),
        stop=stop_after_attempt(5),
        reraise=True,
    )
    def _send_raw_message(self, raw_message: str) -> None:
        service = self._get_service()
        service.users().messages().send(
            userId=str(self.sender_email),
            body={"raw": raw_message},
        ).execute()

    def _build_message(
        self,
        to_email: EmailStr,
        subject: str,
        content: str,
        html: bool = False,
        cc: Optional[Iterable[EmailStr]] = None,
        bcc: Optional[Iterable[EmailStr]] = None,
    ) -> str:
        """Build a raw MIME message for a single recipient."""
        message = MIMEText(content, "html" if html else "plain")
        message["To"] = str(to_email)
        message["From"] = str(self.sender_email)
        message["Subject"] = subject

        if cc:
            message["Cc"] = ", ".join(map(str, cc))
        if bcc:
            message["Bcc"] = ", ".join(map(str, bcc))

        encoded = base64.urlsafe_b64encode(message.as_bytes()).decode("utf-8")
        return encoded
