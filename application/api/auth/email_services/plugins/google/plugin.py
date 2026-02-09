import base64
from email.mime.text import MIMEText
from typing import Iterable, List, Optional
from pydantic import BaseSettings, EmailStr, FilePath, root_validator
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from google.oauth2 import service_account
from concurrent.futures import ThreadPoolExecutor, as_completed


class EmailServiceError(Exception):
    pass


class PluginConfig(BaseSettings):
    service_account_file: FilePath
    sender_email: EmailStr
    scopes: List[str] = ["https://www.googleapis.com/auth/gmail.send"]

    @root_validator
    def validate_service_account(cls, values):
        """Optional: validate service account can connect to Gmail API"""
        from googleapiclient.discovery import build
        from google.oauth2 import service_account

        try:
            credentials = service_account.Credentials.from_service_account_file(
                values['service_account_file'],
                scopes=values['scopes']
            ).with_subject(values['sender_email'])

            service = build("gmail", "v1", credentials=credentials, cache_discovery=False)
            service.users().getProfile(userId="me").execute()
        except Exception as e:
            raise ValueError(f"Invalid Gmail Service Account configuration: {e}")
        return values


class GoogleCloudGmailPlugin:
    """
    Google Cloud Gmail API plugin using Service Account.

    Requirements:
    - Google Workspace account
    - Domain-wide delegation for the service account
    """

    def __init__(self, config: PluginConfig):
        self.config = config
        self.sender_email = config.sender_email

        credentials = service_account.Credentials.from_service_account_file(
            config.service_account_file,
            scopes=config.scopes
        ).with_subject(config.sender_email)

        self.service = build("gmail", "v1", credentials=credentials, cache_discovery=False)

    def test_connection(self) -> None:
        try:
            self.service.users().getProfile(userId="me").execute()
        except HttpError as exc:
            raise EmailServiceError("Gmail API credentials invalid or expired") from exc

    def send_email(
        self,
        to_email: EmailStr,
        subject: str,
        content: str,
        html: bool = False,
        cc: Optional[Iterable[EmailStr]] = None,
        bcc: Optional[Iterable[EmailStr]] = None,
    ) -> None:
        """Send a single email"""

        raw_message = self._build_message(to_email, subject, content, html, cc, bcc)
        try:
            self.service.users().messages().send(
                userId="me",
                body={"raw": raw_message},
            ).execute()
        except HttpError as exc:
            error_message = exc.content.decode() if hasattr(exc, "content") else str(exc)
            raise EmailServiceError(f"Gmail API send_email failed: {error_message}") from exc


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
        """Send emails to multiple recipients concurrently and handle exceptions properly."""
        recipient_list = list(recipients)
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            futures = [
                executor.submit(self.send_email, recipient, subject, content, html, cc, bcc)
                for recipient in recipient_list
            ]
            for future in as_completed(futures):
                future.result()    

    def _build_message(
        self,
        to_email: EmailStr,
        subject: str,
        content: str,
        html: bool = False,
        cc: Optional[Iterable[EmailStr]] = None,
        bcc: Optional[Iterable[EmailStr]] = None,
    ) -> str:
        """Builds a Gmail-compatible Base64 encoded email message"""
        message = MIMEText(content, "html" if html else "plain")
        message["To"] = to_email
        message["From"] = self.sender_email
        message["Subject"] = subject

        if cc:
            message["Cc"] = ", ".join(cc)
        if bcc:
            message["Bcc"] = ", ".join(bcc)

        encoded = base64.urlsafe_b64encode(message.as_bytes()).decode("utf-8")
        return encoded
