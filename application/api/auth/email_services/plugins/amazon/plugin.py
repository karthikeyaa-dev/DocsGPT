import threading
import copy
from typing import Iterable, Optional, List
import boto3
from botocore.exceptions import ClientError, EndpointConnectionError
from tenacity import retry, retry_if_exception, wait_exponential_jitter, stop_after_attempt
from pydantic import EmailStr
from concurrent.futures import ThreadPoolExecutor, as_completed
from pydantic_settings import BaseSettings
from .exceptions import EmailServiceError

# ========================
# Config
# ========================

class PluginConfig(BaseSettings):
    aws_access_key_id: str
    aws_secret_access_key: str
    region_name: str = "us-east-1"
    sender_email: EmailStr

# =========================
# Retry Logic
# =========================

def is_retryable_sns_error(exc: Exception) -> bool:
    """Determine if an SNS error is retryable."""
    if isinstance(exc, EndpointConnectionError):
        return True
    if isinstance(exc, ClientError):
        error_code = exc.response.get("Error", {}).get("Code")
        if error_code in {"Throttling", "InternalFailure", "ServiceUnavailable"}:
            return True
    return False

# =========================
# Plugin
# =========================

_thread_local = threading.local()

class AmazonSNSPlugin:
    """
    Amazon SNS plugin for sending emails using AWS SNS.
    """

    def __init__(self, config: PluginConfig, test_credentials: bool = True):
        self.config = config
        self.sender_email = config.sender_email

        self._get_client()

        if test_credentials:
            self.test_connection()

    # =========================
    # Service Helper (Thread-safe)
    # =========================

    def _get_client(self):
        if not hasattr(_thread_local, "client"):
            _thread_local.client = boto3.client(
                "sns",
                aws_access_key_id=self.config.aws_access_key_id,
                aws_secret_access_key=self.config.aws_secret_access_key,
                region_name=self.config.region_name,
            )
        return _thread_local.client

    # =========================
    # Public API
    # =========================

    def test_connection(self) -> None:
        """Test if AWS SNS credentials are valid."""
        try:
            client = self._get_client()
            client.list_topics(MaxResults=1)
        except ClientError as exc:
            raise EmailServiceError("SNS credentials invalid or insufficient permissions") from exc

    def send_email(
        self,
        to_email: EmailStr,
        subject: str,
        content: str,
        html: bool = False,
        cc: Optional[Iterable[EmailStr]] = None,
        bcc: Optional[Iterable[EmailStr]] = None,
    ) -> None:
        if cc or bcc:
            # SNS does not support CC/BCC
            raise EmailServiceError("SNS does not support CC or BCC")

        try:
            self._send_single_email(to_email, subject, content)
        except Exception as exc:
            raise EmailServiceError(f"SNS send_email failed for {to_email}: {str(exc)}") from exc

    def send_bulk_email(
        self,
        recipients: Iterable[EmailStr],
        subject: str,
        content: str,
        html: bool = False,
        max_workers: int = 5,
    ) -> None:
        recipient_list = list(recipients)
        errors = []

        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            futures = {
                executor.submit(
                    self._send_single_email,
                    recipient,
                    subject,
                    content,
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

    @retry(
        retry=retry_if_exception(is_retryable_sns_error),
        wait=wait_exponential_jitter(initial=1, max=30),
        stop=stop_after_attempt(5),
        reraise=True,
    )
    def _send_single_email(self, to_email: EmailStr, subject: str, content: str) -> None:
        client = self._get_client()
        try:
            client.publish(
                TargetArn=f"arn:aws:sns:{self.config.region_name}:{self._get_account_id()}:email-topic",
                Message=content,
                Subject=subject,
                MessageStructure="string",  # Simple string message
                MessageAttributes={
                    "AWS.SNS.SMS.SenderID": {
                        "DataType": "String",
                        "StringValue": str(self.sender_email),
                    }
                }
            )
        except ClientError as exc:
            raise EmailServiceError(f"SNS publish failed: {exc}") from exc

    def _get_account_id(self) -> str:
        """Helper to get AWS account ID for SNS ARN."""
        sts = boto3.client(
            "sts",
            aws_access_key_id=self.config.aws_access_key_id,
            aws_secret_access_key=self.config.aws_secret_access_key,
            region_name=self.config.region_name,
        )
        return sts.get_caller_identity()["Account"]
