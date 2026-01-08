# application/api/auth/models.py
import uuid
import re
from datetime import datetime, timezone
from sqlalchemy import String, Boolean, DateTime, Enum as SAEnum, ForeignKey
from sqlalchemy.sql import text
from sqlalchemy import Column, Index, func
from sqlalchemy.orm import (
    Mapped,
    mapped_column,
    relationship,
    validates,
    declarative_base,
)
from email_validator import validate_email, EmailNotValidError
from application.api.auth.utils.hash import (
    get_password_hash,
    is_password_hashed,
    verify_password,
)
from application.extensions import db
from enum import Enum
from typing import Optional
from sqlalchemy.dialects.postgresql import UUID

Base = db.Model  # Use db.Model as the base class for your models


def utcnow():
    return datetime.now(timezone.utc)


class UserRole(Enum):
    """Enum for user roles"""

    USER = "user"
    ADMIN = "admin"


class User(Base):
    """User model for the `users` table"""

    __tablename__ = "users"

    id: Mapped[uuid.UUID] = mapped_column(
        primary_key=True,
        default=uuid.uuid4,
    )

    email: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
        index=True,
    )

    _password: Mapped[str] = mapped_column(
        "password",
        String(512),
        nullable=False,
    )

    role: Mapped[UserRole] = mapped_column(
        nullable=False,
        default=UserRole.USER,
    )

    is_active: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=True,
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=text("CURRENT_TIMESTAMP"),
        nullable=False,
    )

    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=text("CURRENT_TIMESTAMP"),
        onupdate=text("CURRENT_TIMESTAMP"),
        nullable=False,
    )

    refresh_tokens: Mapped[list["RefreshToken"]] = relationship(
        "RefreshToken",
        back_populates="user",
        cascade="all, delete-orphan",
        lazy="selectin",
    )

    __table_args__ = (
        Index(
            "uq_users_email_lower",
            func.lower(email),
            unique=True,
        ),
    )

    # ------------------------------------------------------------------
    # Email validation & normalization
    # ------------------------------------------------------------------

    @validates("email")
    def validate_email_address(self, key, value: str) -> str:
        try:
            valid = validate_email(value.strip())
            return valid.email.lower()
        except EmailNotValidError as exc:
            raise ValueError(f"Invalid email address: {exc}") from exc

    # ------------------------------------------------------------------
    # Password handling (WRITE-ONLY)
    # ------------------------------------------------------------------

    @property
    def password(self):
        raise AttributeError("Password is write-only")

    @password.setter
    def password(self, raw_password: str):
        self._password = self._validate_and_hash_password(raw_password)

    def check_password(self, raw_password: str) -> bool:
        """Verify a raw password against the stored hash"""
        return verify_password(raw_password, self._password)

    def _validate_and_hash_password(self, password: str) -> str:
        if not password:
            raise ValueError("Password is required")

        if is_password_hashed(password):
            return password

        if len(password) < 8:
            raise ValueError("Password must be at least 8 characters long")

        if len(password) > 72:
            raise ValueError("Password must be 72 characters or fewer")

        if not re.search(r"[A-Za-z]", password):
            raise ValueError("Password must contain at least one letter")

        if not re.search(r"[0-9]", password):
            raise ValueError("Password must contain at least one number")

        if not re.search(r"[!@#$%^&*(),.?\":{}|<>]", password):
            raise ValueError("Password must contain at least one special character")

        return get_password_hash(password)


class RefreshToken(Base):
    __tablename__ = "refresh_tokens"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    jti: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        unique=True,
        nullable=False,
        index=True,
    )

    parent_jti: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("refresh_tokens.jti", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )

    child_jti: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("refresh_tokens.jti", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )

    expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
    )

    revoked: Mapped[bool] = mapped_column(
        Boolean,
        default=False,
        nullable=False,
        index=True,  # speeds up queries filtering active/revoked tokens
    )

    revoked_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),  # <-- sets the default timestamp
        nullable=False,
    )

    used_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    ip_address: Mapped[Optional[str]] = mapped_column(
        String(45),
        nullable=True,
    )

    device_id: Mapped[str] = mapped_column(
        String(255),
        nullable=False,  # enforce non-null for tracking
        index=True,
    )

    user_agent: Mapped[Optional[str]] = mapped_column(
        String(255),
        nullable=True,
    )

    user: Mapped["User"] = relationship(
        "User",
        back_populates="refresh_tokens",
    )

    @validates("jti")
    def validate_jti(self, key, value):
        if not isinstance(value, uuid.UUID):
            raise ValueError("jti must be a UUID")
        return value

    @validates("expires_at")
    def validate_expiration(self, key, value):
        if value <= utcnow():
            raise ValueError("expires_at must be in the future")
        return value
