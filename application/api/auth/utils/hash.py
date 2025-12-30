import logging
from passlib.context import CryptContext

# Initialize the password context to use bcrypt hashing
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


def get_password_hash(password: str) -> str:
    password = password[:72]  # Ensure truncation is applied before hashing
    hashed_password = pwd_context.hash(password)

    # Log the length of the generated hash
    logging.debug(f"Generated hash length: {len(hashed_password)}")
    logging.debug(f"Generated hash: {hashed_password}")

    return hashed_password


def verify_password(plain_password: str, hashed_password: str) -> bool:
    # Verify if the plain password matches the hashed password
    return pwd_context.verify(plain_password, hashed_password)


def is_password_hashed(value: str) -> bool:
    return value.startswith("$2")  # or more sophisticated check
