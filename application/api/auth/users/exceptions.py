# application/api/auth/users/exceptions.py
class ApplicationError(Exception):
    """
    Base class for all domain exceptions with flexible messages and status codes.
    Can be raised with a custom message and/or HTTP status code.
    """

    status_code: int = 400
    default_message: str = "Application error"

    def __init__(self, message: str | None = None, status_code: int | None = None):
        self.message = message or self.default_message
        if status_code is not None:
            self.status_code = status_code
        super().__init__(self.message)


class UserAlreadyRegistered(ApplicationError):
    status_code = 409
    default_message = "User already registered"


class UserNotFound(ApplicationError):
    status_code = 404
    default_message = "User not found"


class InvalidCredentials(ApplicationError):
    status_code = 401
    default_message = "Invalid credentials"


class InvalidEmail(ApplicationError):
    status_code = 422
    default_message = "Invalid email address"


class PasswordValidationError(ApplicationError):
    status_code = 422
    default_message = "Invalid password"


# Database connection errors
class DatabaseConnectionError(ApplicationError):
    status_code = 500
    default_message = "Database connection error"


# Optional: generic error for token issues
class TokenError(ApplicationError):
    status_code = 401
    default_message = "Invalid or expired token"


class MissingDeviceID(ApplicationError):
    status_code = 400
    default_message = "device_id is required"


# Usage examples:
# raise UserAlreadyRegistered()
# raise UserAlreadyRegistered("Email already exists in the system")
# raise InvalidCredentials("Password incorrect")
