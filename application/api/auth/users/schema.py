from pydantic import BaseModel, EmailStr, field_validator
from uuid import UUID
from typing import Optional
from enum import Enum
from application.api.auth.models import UserRole
import re
from datetime import datetime, timezone


class UserCreate(BaseModel):
    email: EmailStr
    password: str
    role: UserRole = UserRole.USER

    # Normalize email to lowercase
    @field_validator("email")
    @classmethod
    def normalize_email(cls, v):
        return v.strip.lower()

    # Validate password complexity
    @field_validator("password")
    @classmethod
    def validate_password(cls, v: str) -> str:
        if len(v) < 8:
            raise ValueError("Password must be at least 8 characters long")

        # At least one uppercase letter
        if not re.search(r"[A-Z]", v):
            raise ValueError("Password must contain at least one uppercase letter")

        # At least one lowercase letter
        if not re.search(r"[a-z]", v):
            raise ValueError("Password must contain at least one lowercase letter")

        # At least one digit
        if not re.search(r"\d", v):
            raise ValueError("Password must contain at least one digit")

        # At least one special character
        if not re.search(r"[!@#$%^&*(),.?\":{}|<>]", v):
            raise ValueError("Password must contain at least one special character")

        # Invalid characters check
        if re.search(r"[\'\"\\\s`;&$]", v):
            raise ValueError("Password contains invalid characters")

        return v


class UserResponse(BaseModel):
    id: UUID
    email: str
    role: str
    is_active: bool
    created_at: datetime

    class Config:
        orm_mode = True


class UserLogin(BaseModel):
    email: EmailStr
    password: str


class TokenType(str, Enum):
    ACCESS = "Access"
    REFRESH = "Refresh"


# Base payload shared by both access and refresh tokens
class BaseJwtPayload(BaseModel):
    sub: str  # User ID
    jti: str  # Unique token ID
    iat: int  # Issued at timestamp
    exp: int  # Expiry timestamp
    nbf: Optional[int] = None  # Not valid before
    iss: Optional[str] = None  # Issuer
    aud: Optional[str] = None  # Audience
    type: TokenType

    # Convenience properties to get datetime objects
    @property
    def issued_at(self) -> datetime:
        return datetime.fromtimestamp(self.iat)

    @property
    def expires_at(self) -> datetime:
        return datetime.fromtimestamp(self.exp)

    @property
    def not_before(self) -> Optional[datetime]:
        if self.nbf is not None:
            return datetime.fromtimestamp(self.nbf)
        return None


# Access token payload
class JwtPayload(BaseJwtPayload):
    email: str
    role: str
    type: TokenType = TokenType.ACCESS


# Refresh token payload
class RefreshJwtPayload(BaseJwtPayload):
    type: TokenType = TokenType.REFRESH


# Encoded JWT token with decoded payload
class JwtTokenSchema(BaseModel):
    token: str  # Encoded JWT string
    payload: JwtPayload

    @property
    def expire(self) -> datetime:
        return self.payload.expires_at

    @property
    def issuer(self) -> Optional[str]:
        return self.payload.iss

    @property
    def audience(self) -> Optional[str]:
        return self.payload.aud

    def is_valid(self) -> bool:
        now = datetime.utcnow()
        if self.payload.nbf and now < self.payload.not_before:
            return False
        if now > self.payload.expires_at:
            return False
        return True


# Encoded refresh token with decoded payload
class RefreshTokenSchema(BaseModel):
    token: str  # Encoded JWT string
    payload: RefreshJwtPayload

    @property
    def expire(self) -> datetime:
        return self.payload.expires_at

    @property
    def issuer(self) -> Optional[str]:
        return self.payload.iss

    @property
    def audience(self) -> Optional[str]:
        return self.payload.aud

    def is_valid(self) -> bool:
        now = datetime.utcnow()
        if self.payload.nbf and now < self.payload.not_before:
            return False
        if now > self.payload.expires_at:
            return False
        return True


# Combined token pair (access + refresh)
class TokenPair(BaseModel):
    access: JwtTokenSchema
    refresh: RefreshTokenSchema


class UserLogin(BaseModel):
    email: EmailStr
    password: str
    device_id: UUID


class LoginResponse(BaseModel):
    access_token: str
    access_jti: str  # Access token unique ID
    refresh_token: str
    refresh_jti: str  # Refresh token unique ID
    token_type: str = "bearer"


class RefreshTokenInputSchema(BaseModel):
    refresh_token: str
    device_id: str
