import jwt
from datetime import datetime, timedelta, timezone
from sqlalchemy import text
from sqlalchemy.orm import Session
from uuid import uuid4
from uuid import UUID
from typing import Optional, List
from application.api.auth.models import (
    User,
    RefreshToken,
)
from application.api.auth.users.schema import (
    JwtPayload,
    JwtTokenSchema,
    TokenType,
    RefreshTokenSchema,
    RefreshJwtPayload,
    TokenPair,
    LoginResponse,
)
from application.api.auth.users.exceptions import TokenError
from application.api.auth.config import CONFIG


def create_access_token(
    *,
    user_id: str,
    email: str,
    role: str,
    secret_key: str = CONFIG.JWT_SECRET_KEY,
    issuer: str = "DocsGPT",
    audience: str = "Users",
    expires_in_minutes: int = CONFIG.ACCESS_TOKEN_EXPIRE_IN_MINUTES,
) -> JwtTokenSchema:
    """
    Create a signed JWT access token
    """

    now = datetime.now(tz=timezone.utc)
    exp = now + timedelta(minutes=expires_in_minutes)

    payload = JwtPayload(
        sub=user_id,
        email=email,
        role=role,
        jti=str(uuid4()),
        iat=int(now.timestamp()),
        exp=int(exp.timestamp()),
        iss=issuer,
        aud=audience,
        type=TokenType.ACCESS.value,
    )

    # ⚠ Pass dict, not Pydantic model
    encoded_token = jwt.encode(
        payload.model_dump(exclude_none=True),
        secret_key,
        algorithm=CONFIG.JWT_ALGORITHM,
        headers={
            "typ": CONFIG.JWT_TYP,
            "kid": CONFIG.JWT_KID,
        },
    )

    return JwtTokenSchema(
        token=encoded_token,
        payload=payload,
    )


def create_refresh_token(
    *,
    user_id: str,
    secret_key: str = CONFIG.JWT_SECRET_KEY,
    issuer: str = "DocsGPT",
    audience: str = "Users",
    expires_in_days: int = CONFIG.REFRESH_TOKEN_EXPIRE_IN_MINUTES,
) -> RefreshTokenSchema:
    """
    Create a signed JWT refresh token
    """

    now = datetime.now(tz=timezone.utc)
    exp = now + timedelta(days=expires_in_days)

    payload = RefreshJwtPayload(
        sub=user_id,
        jti=str(uuid4()),
        iat=int(now.timestamp()),
        exp=int(exp.timestamp()),
        iss=issuer,
        aud=audience,
        type=TokenType.REFRESH.value,
    )

    encoded_token = jwt.encode(
        payload.model_dump(exclude_none=True),
        secret_key,
        algorithm=CONFIG.JWT_ALGORITHM,
        headers={
            "typ": CONFIG.JWT_TYP,
            "kid": CONFIG.JWT_KID,
        },
    )

    return RefreshTokenSchema(
        token=encoded_token,
        payload=payload,
    )


def create_token_pair(user_id: str, email: str, role: str) -> TokenPair:
    access = create_access_token(user_id=user_id, email=email, role=role)
    refresh = create_refresh_token(user_id=user_id)
    return TokenPair(access=access, refresh=refresh)


def save_refresh_token(
    db: Session,
    user_id: UUID,
    jti: UUID,
    expires_at: datetime,
    device_id: str,
    parent_jti: Optional[UUID] = None,
    ip_address: Optional[str] = None,
    user_agent: Optional[str] = None,
) -> RefreshToken:
    token = RefreshToken(
        user_id=user_id,
        jti=jti,
        parent_jti=parent_jti,
        expires_at=expires_at,
        device_id=device_id,  # now comes from parameter
        ip_address=ip_address,
        user_agent=user_agent,
        used_at=None,
    )
    db.add(token)
    db.commit()
    db.refresh(token)
    return token


def decode_refresh_token(token: str) -> dict:
    """
    Decode a JWT refresh token and verify its type.
    """
    decoded = jwt.decode(
        token,
        CONFIG.JWT_SECRET_KEY,
        algorithms=[CONFIG.JWT_ALGORITHM],
        audience="Users",
        options={"verify_exp": True},
    )
    # Ensure type matches what was encoded
    if decoded.get("type") != TokenType.REFRESH.value:
        raise ValueError("Invalid token type")
    return decoded


def validate_refresh_token(
    db: Session, user_id: UUID, jti: UUID, ip_address: str, user_agent: str
) -> RefreshToken:
    token: RefreshToken = (
        db.query(RefreshToken).filter_by(jti=jti, user_id=user_id).first()
    )
    if not token or token.revoked or token.expires_at < datetime.now(timezone.utc):
        raise ValueError("Invalid or expired refresh token")
    if token.ip_address != ip_address or token.user_agent != user_agent:
        raise ValueError("Token used from unrecognized client")
    return token


def rotate_refresh_token(
    db: Session,
    old_jti: str,
    user_id: UUID,
    device_id: Optional[str] = None,
    ip_address: Optional[str] = None,
    user_agent: Optional[str] = None,
) -> RefreshToken:
    """
    Rotate a refresh token:
    1. Mark the old token as used and revoked
    2. Create a new refresh token with parent_jti linking to old token
    3. Preserve device_id, IP, and User-Agent
    """

    now = datetime.now(timezone.utc)

    # Fetch the old token
    old_token: RefreshToken = (
        db.query(RefreshToken).filter_by(jti=old_jti, user_id=user_id).first()
    )

    if not old_token or old_token.revoked or old_token.expires_at < now:
        raise ValueError("Invalid or expired refresh token")

    # Mark old token as used and revoked
    old_token.revoked = True
    old_token.revoked_at = now
    old_token.used_at = now
    db.add(old_token)

    # Create new refresh token
    new_refresh = create_refresh_token(user_id=str(user_id))

    # Save new token in DB with parent_jti and client info
    save_refresh_token(
        db=db,
        user_id=user_id,
        jti=UUID(new_refresh.payload.jti),
        parent_jti=old_token.jti,
        device_id=device_id or old_token.device_id,  # inherit device if not provided
        ip_address=ip_address or old_token.ip_address,
        user_agent=user_agent or old_token.user_agent,
        expires_at=datetime.fromtimestamp(new_refresh.payload.exp, tz=timezone.utc),
    )

    db.commit()
    return new_refresh


def generate_new_tokens(
    db: Session, user: User, old_token: RefreshToken, ip_address: str, user_agent: str
) -> LoginResponse:
    """Rotate refresh token and create a new access token."""
    new_refresh = rotate_refresh_token(
        db=db,
        old_jti=old_token.jti,
        user_id=old_token.user_id,
        ip_address=ip_address,
        user_agent=user_agent,
    )

    new_access = create_access_token(
        user_id=str(user.id), email=user.email, role=user.role
    )

    return LoginResponse(
        access_token=new_access.token,
        access_jti=new_access.payload.jti,
        refresh_token=new_refresh.token,
        refresh_jti=new_refresh.payload.jti,
        token_type="bearer",
    )


def revoke_token_family(db: Session, root_jti: UUID):
    now = datetime.now(timezone.utc)

    db.execute(
        text(
            """
        WITH RECURSIVE token_tree AS (
            SELECT jti FROM refresh_tokens WHERE jti = :root
            UNION ALL
            SELECT rt.jti
            FROM refresh_tokens rt
            JOIN token_tree tt ON rt.parent_jti = tt.jti
        )
        UPDATE refresh_tokens
        SET revoked = TRUE,
            revoked_at = :now
        WHERE jti IN (SELECT jti FROM token_tree)
        """
        ),
        {"root": str(root_jti), "now": now},
    )


def audit_token_environment(old_token, ip_address, user_agent):
    if old_token.user_agent != user_agent:
        pass  # intentional
    if old_token.ip_address != ip_address:
        pass  # intentional


def recreate_refresh_token(refresh_token: RefreshToken) -> RefreshTokenSchema:
    """
    Re-create the refresh JWT from DB state for idempotent retry.
    - Uses existing jti
    - Uses existing created_at / expires_at
    - Preserves type, iss, aud, nbf
    - Fully validated via Pydantic
    """

    now = datetime.now(timezone.utc)
    if refresh_token.expires_at <= now:
        raise TokenError("Refresh token expired")

    payload = RefreshJwtPayload(
        sub=str(refresh_token.user_id),
        jti=str(refresh_token.jti),
        iat=int(refresh_token.created_at.timestamp()),
        exp=int(refresh_token.expires_at.timestamp()),
        # nbf=int(refresh_token.created_at.timestamp()),  # optional, sets "not before"
        iss="DocsGPT",  # replace with config/env if needed
        aud="User",  # replace with config/env if needed
        type=TokenType.REFRESH,
    )

    token = jwt_encode(payload.model_dump(exclude_none=True))

    return RefreshTokenSchema(token=token, payload=payload)


"""def create_token_pair_with_db(
    db: Session, user_id: UUID, email: str, role: str, ip_address=None, user_agent=None
):
    # Access token
    access = create_access_token(user_id=str(user_id), email=email, role=role)

    # Refresh token
    refresh = create_refresh_token(user_id=str(user_id))
    save_refresh_token(
        db,
        user_id=user_id,
        jti=refresh.payload.jti,
        expires_at=datetime.fromtimestamp(refresh.payload.exp, tz=timezone.utc),
        ip_address=ip_address,
        user_agent=user_agent,
    )

    return TokenPair(access=access, refresh=refresh)"""
