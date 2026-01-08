# main.py
from flask import Flask, Blueprint, request
from flask_sqlalchemy import SQLAlchemy
from flask_migrate import Migrate
from application.api.auth.models import (
    User,
    UserRole,
    RefreshToken,
)
from application.api.auth.utils.db_connection import DBConnection
from application.api.auth.users.schema import (
    UserCreate,
    UserResponse,
    UserLogin,
    LoginResponse,
    RefreshTokenSchema,
    RefreshTokenInputSchema,
)
from application.api.auth.utils.hash import verify_password
from application.api.auth.users.exceptions import (
    ApplicationError,
    UserAlreadyRegistered,
    UserNotFound,
    InvalidCredentials,
    PasswordValidationError,
    TokenError,
    MissingDeviceID,
)
from application.api.auth.utils.validation_schema import validate_schema
from application.extensions import db
from application.api.auth.utils.hash import get_password_hash
from application.api.auth.users.jwt import (
    create_token_pair,
    save_refresh_token,
    create_access_token,
    decode_refresh_token,
    create_refresh_token,
    validate_refresh_token,
    generate_new_tokens,
    revoke_token_family,
    rotate_refresh_token,
    audit_token_environment,
)
from datetime import datetime, timezone
from uuid import UUID
from sqlalchemy.exc import IntegrityError

auth = Blueprint("auth", __name__, url_prefix="/api/auth")


@auth.route("/register", methods=["POST"])
@validate_schema(input_schema=UserCreate, response_schema=UserResponse)
def register_user(validated_data):
    data = validated_data
    try:
        with db.session.begin():
            user = User(
                email=data.email,
                # INFO : We are hashing the password at database level, so we are not hashing at application level if we hash here we may get dual hashig problem
                password=data.password,  
                role=data.role,
                is_active=True,
            )
            db.session.add(user)

        return UserResponse(
            id=user.id,
            email=user.email,
            role=user.role,
            is_active=user.is_active,
            created_at=user.created_at,
        )

    except IntegrityError:
        raise UserAlreadyRegistered("User already registered with that email")


@auth.route("/login", methods=["POST"])
@validate_schema(input_schema=UserLogin, response_schema=LoginResponse)
def login_user(validated_data):
    # INFO : We are normalizing the email in the schema
    email = validated_data.email
    password = validated_data.password
    device_id = getattr(validated_data, "device_id", None)

    if not device_id:
        raise MissingDeviceID()

    try:
        user = db.session.query(User).filter(User.email == email).first()
        if not user:
            raise UserNotFound()
        if not user.is_active:
            raise InvalidCredentials("User is inactive")

        if not user.check_password(password):
            raise InvalidCredentials("Password is Incorrect")

        token_pair = create_token_pair(
            user_id=str(user.id), email=user.email, role=user.role
        )

        ip_address = request.headers.get("X-Forwarded-For", request.remote_addr)
        user_agent = request.headers.get("User-Agent")

        save_refresh_token(
            db=db.session,
            user_id=user.id,
            jti=UUID(token_pair.refresh.payload.jti),
            parent_jti=None,
            device_id=device_id,
            ip_address=ip_address,
            user_agent=user_agent,
            expires_at=datetime.fromtimestamp(
                token_pair.refresh.payload.exp, tz=timezone.utc
            ),
        )

        return LoginResponse(
            access_token=token_pair.access.token,
            access_jti=token_pair.access.payload.jti,
            refresh_token=token_pair.refresh.token,
            refresh_jti=token_pair.refresh.payload.jti,
            token_type="bearer",
        )

    except ApplicationError:
        db.session.rollback()
        raise

    except Exception as e:
        db.session.rollback()
        raise ApplicationError(str(e))


'''@auth.route("/refresh", methods=["POST"])
@validate_schema(input_schema=RefreshTokenInputSchema, response_schema=LoginResponse)
def refresh_token_endpoint(validated_data):
    refresh_token_str = validated_data.refresh_token
    device_id = validated_data.device_id

    if not device_id:
        raise MissingDeviceID()

    # NOTE : Take this from frontend
    ip_address = request.headers.get("X-Forwarded-For", request.remote_addr)
    # NOTE : Take this from frontend
    user_agent = request.headers.get("User-Agent")
    # NOTE : Take this from frontend
    now = datetime.now(timezone.utc)

    try:
        decoded = decode_refresh_token(refresh_token_str)
        user_id = UUID(decoded["sub"])
        jti = UUID(decoded["jti"])
    except Exception:
        raise TokenError("Invalid refresh token. Please login again.")

    try:
        with db.session.begin():
            old_token: RefreshToken | None = (
                db.session.query(RefreshToken)
                .filter_by(jti=jti, user_id=user_id)
                .with_for_update()
                .first()
            )

            if not old_token:
                raise TokenError("Invalid refresh token. Please login again.")

            if (
                old_token.revoked
                or old_token.used_at is not None
                or old_token.expires_at < now
                or old_token.device_id != device_id
            ):
                # INFO : We are revoking the token family if we found old token is used
                revoke_token_family(
                    db=db.session,
                    root_jti=old_token.parent_jti or old_token.jti,
                )
                raise TokenError("Invalid refresh token. Please login again.")

            # TODO : Write the proper function for auditing the environment
            if audit_token_environment(old_token, ip_address, user_agent):
                revoke_token_family(
                    db=db.session,
                    root_jti=old_token.parent_jti or old_token.jti,
                )
                raise TokenError("Suspicious refresh attempt detected.")

            # INFO : Marking the user passed token as used for generating new one
            old_token.used_at = now
            old_token.revoked = True
            old_token.revoked_at = now

            # INFO : Created new refresh token
            new_refresh_jwt = create_refresh_token(user_id=str(user_id))

            # INFO : Writing into the database about the newly generated refresh token
            new_refresh = RefreshToken(
                user_id=user_id,
                jti=UUID(new_refresh_jwt.payload.jti),
                parent_jti=old_token.jti,
                device_id=device_id,
                ip_address=ip_address,
                user_agent=user_agent,
                expires_at=datetime.fromtimestamp(
                    new_refresh_jwt.payload.exp, tz=timezone.utc
                ),
                revoked=False,
            )
            db.session.add(new_refresh)

        # INFO : Creating new access token
        access = create_access_token(
            user_id=str(old_token.user_id),
            email=old_token.user.email,
            role=old_token.user.role,
        )

        return LoginResponse(
            access_token=access.token,
            access_jti=access.payload.jti,
            refresh_token=new_refresh_jwt.token,
            refresh_jti=new_refresh_jwt.payload.jti,
            token_type="bearer",
        )

    except ApplicationError:
        db.session.rollback()
        raise

    except Exception as e:
        db.session.rollback()
        raise ApplicationError(str(e))
        # FIX : This comment is used to understand the git stash'''


@auth.route("/refresh", methods=["POST"])
@validate_schema(input_schema=RefreshTokenInputSchema, response_schema=LoginResponse)
def refresh_token_endpoint(validated_data):
    refresh_token_str = validated_data.refresh_token
    device_id = validated_data.device_id

    if not device_id:
        raise MissingDeviceID()

    ip_address = request.headers.get("X-Forwarded-For", request.remote_addr)
    user_agent = request.headers.get("User-Agent")
    now = datetime.now(timezone.utc)

    # 1️⃣ Decode refresh token (outside transaction)
    try:
        decoded = decode_refresh_token(refresh_token_str)
        user_id = UUID(decoded["sub"])
        jti = UUID(decoded["jti"])
    except Exception:
        raise TokenError("Invalid refresh token. Please login again.")

    try:
        with db.session.begin():

            # 2️⃣ Lock refresh token row
            old_token: RefreshToken | None = (
                db.session.query(RefreshToken)
                .filter_by(jti=jti, user_id=user_id)
                .with_for_update()
                .first()
            )

            if not old_token:
                raise TokenError("Invalid refresh token. Please login again.")

            # 3️⃣ Hard-fail conditions (always revoke)
            if old_token.expires_at < now or old_token.device_id != device_id:
                revoke_token_family(
                    db=db.session,
                    root_jti=old_token.parent_jti or old_token.jti,
                )
                raise TokenError("Invalid refresh token. Please login again.")

            # 4️⃣ Token already used → retry OR attack
            if old_token.used_at is not None:

                # 4a️⃣ Environment mismatch → replay attack
                if audit_token_environment(old_token, ip_address, user_agent):
                    revoke_token_family(
                        db=db.session,
                        root_jti=old_token.parent_jti or old_token.jti,
                    )
                    raise TokenError("Refresh token reuse detected.")

                # 4b️⃣ Idempotent retry → return already-issued child
                child = (
                    db.session.query(RefreshToken)
                    .filter_by(jti=old_token.child_jti, revoked=False)
                    .first()
                )

                if not child or child.expires_at < now:
                    raise TokenError("Session expired. Please login again.")

                access = create_access_token(
                    user_id=str(old_token.user_id),
                    email=old_token.user.email,
                    role=old_token.user.role,
                )

                refresh_jwt = recreate_refresh_jwt(child)

                return LoginResponse(
                    access_token=access.token,
                    access_jti=access.payload.jti,
                    refresh_token=refresh_jwt.token,
                    refresh_jti=refresh_jwt.payload.jti,
                    token_type="bearer",
                )

            # 5️⃣ Normal rotation (first valid use)
            if audit_token_environment(old_token, ip_address, user_agent):
                revoke_token_family(
                    db=db.session,
                    root_jti=old_token.parent_jti or old_token.jti,
                )
                raise TokenError("Suspicious refresh attempt detected.")

            # Mark old token as used
            old_token.used_at = now
            old_token.revoked = True
            old_token.revoked_at = now

            # Create new refresh token
            new_refresh_jwt = create_refresh_token(user_id=str(user_id))

            new_refresh = RefreshToken(
                user_id=user_id,
                jti=UUID(new_refresh_jwt.payload.jti),
                parent_jti=old_token.jti,
                device_id=device_id,
                ip_address=ip_address,
                user_agent=user_agent,
                expires_at=datetime.fromtimestamp(
                    new_refresh_jwt.payload.exp, tz=timezone.utc
                ),
                revoked=False,
            )

            # 🔑 Link parent → child (IDEMPOTENCY)
            old_token.child_jti = new_refresh.jti

            db.session.add(new_refresh)

        # 6️⃣ Issue access token AFTER commit
        access = create_access_token(
            user_id=str(old_token.user_id),
            email=old_token.user.email,
            role=old_token.user.role,
        )

        return LoginResponse(
            access_token=access.token,
            access_jti=access.payload.jti,
            refresh_token=new_refresh_jwt.token,
            refresh_jti=new_refresh_jwt.payload.jti,
            token_type="bearer",
        )

    except ApplicationError:
        raise

    except Exception as e:
        raise ApplicationError(str(e))
