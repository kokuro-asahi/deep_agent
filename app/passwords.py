"""Salted password storage without an additional runtime dependency."""

import hashlib
import secrets


ITERATIONS = 600_000


def hash_password(password: str) -> str:
    salt = secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), ITERATIONS)
    return f"pbkdf2_sha256${ITERATIONS}${salt}${digest.hex()}"


def verify_password(password: str, encoded: str) -> bool:
    try:
        algorithm, rounds, salt, digest = encoded.split("$")
        if algorithm != "pbkdf2_sha256" or int(rounds) != ITERATIONS:
            return False
        actual = hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), int(rounds))
        return secrets.compare_digest(actual.hex(), digest)
    except (ValueError, TypeError, AttributeError):
        return False


# Unknown accounts still perform the same password derivation as known ones.
DUMMY_PASSWORD_HASH = hash_password(secrets.token_urlsafe(32))
