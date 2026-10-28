"""Cross-platform encrypted AEM token storage.

Long tokens are encrypted using Fernet.
Encryption keys are stored in the OS credential vault.

No plaintext fallback is permitted.
"""

import base64
import hashlib
import json
import os
import time
from pathlib import Path

import keyring
from cryptography.fernet import Fernet, InvalidToken
from keyring.errors import PasswordDeleteError

# The service name is part of where existing tokens are stored; renaming it
# would make previously saved tokens unreadable.
SERVICE = "web-technology-inspector/aem-v103"

LEGACY_SERVICE = "web-technology-inspector/aem"

DATA_DIR = (
    Path.home()
    / ".web-technology-inspector"
    / "credentials"
)


def _identity(environment):
    value = (
        str(environment["id"])
        + "|"
        + environment["author_base"].rstrip("/")
    )

    return hashlib.sha256(
        value.encode("utf-8")
    ).hexdigest()


def _legacy_key(environment):
    return (
        str(environment["id"])
        + "|"
        + environment["author_base"].rstrip("/")
    )


def _credential_path(environment):
    return DATA_DIR / (_identity(environment) + ".enc")


def _require_keyring():
    backend = keyring.get_keyring()

    if getattr(backend, "priority", 0) <= 0:
        raise RuntimeError(
            "No secure OS credential vault is available"
        )

    name = (
        backend.__class__.__module__
        + "."
        + backend.__class__.__name__
    ).lower()

    if any(
        item in name
        for item in ("plaintext", "fail", "null")
    ):
        raise RuntimeError(
            "Insecure credential backend rejected"
        )


def _ensure_directory():
    DATA_DIR.mkdir(
        parents=True,
        exist_ok=True
    )

    if os.name != "nt":
        os.chmod(DATA_DIR, 0o700)


def _get_encryption_key(environment, create=False):
    _require_keyring()

    identity = _identity(environment)

    key = keyring.get_password(
        SERVICE,
        identity
    )

    if key:
        return key.encode("ascii")

    if not create:
        return None

    generated = Fernet.generate_key()

    keyring.set_password(
        SERVICE,
        identity,
        generated.decode("ascii")
    )

    return generated


def save_token(environment, token):
    """Encrypt and persist a token of arbitrary practical length."""

    if not isinstance(token, str) or not token.strip():
        raise ValueError("Token cannot be empty")

    token = token.strip()

    if len(token.encode("utf-8")) > 1024 * 1024:
        raise ValueError("Token exceeds the 1 MB safety limit")

    _ensure_directory()

    key = _get_encryption_key(
        environment,
        create=True
    )

    encrypted = Fernet(key).encrypt(
        token.encode("utf-8")
    )

    destination = _credential_path(environment)
    temporary = destination.with_suffix(".tmp")

    try:
        with open(temporary, "wb") as handle:
            handle.write(encrypted)

        if os.name != "nt":
            os.chmod(temporary, 0o600)

        os.replace(temporary, destination)

    finally:
        if temporary.exists():
            temporary.unlink()


def get_token(environment):
    """Retrieve token from encrypted storage or legacy vault."""

    destination = _credential_path(environment)

    if destination.exists():
        key = _get_encryption_key(
            environment,
            create=False
        )

        if not key:
            raise RuntimeError(
                "Encryption key unavailable"
            )

        try:
            encrypted = destination.read_bytes()

            return Fernet(key).decrypt(
                encrypted
            ).decode("utf-8")

        except InvalidToken as exc:
            raise RuntimeError(
                "Stored credential could not be decrypted"
            ) from exc

    # Backward compatibility with earlier short tokens.
    _require_keyring()

    return keyring.get_password(
        LEGACY_SERVICE,
        _legacy_key(environment)
    )


def delete_token(environment):
    """Remove encrypted token and associated credential keys."""

    destination = _credential_path(environment)

    if destination.exists():
        destination.unlink()

    _require_keyring()

    for service, identity in (
        (SERVICE, _identity(environment)),
        (LEGACY_SERVICE, _legacy_key(environment)),
    ):
        try:
            keyring.delete_password(service, identity)
        except PasswordDeleteError:
            pass


def token_status(environment, session_token=None):
    """Report local token availability and advisory JWT expiry."""

    try:
        token = (
            session_token
            if session_token
            else get_token(environment)
        )

    except Exception as exc:
        return {
            "status": "unavailable",
            "message": (
                "Credential storage unavailable: "
                + type(exc).__name__
            ),
            "token": None
        }

    if not token:
        return {
            "status": "missing",
            "message": "No token configured",
            "token": None
        }

    parts = token.split(".")

    if len(parts) == 3:
        try:
            payload = parts[1]
            payload += "=" * (-len(payload) % 4)

            decoded = json.loads(
                base64.urlsafe_b64decode(payload)
            )

            expiry = decoded.get("exp")

            if (
                isinstance(expiry, (int, float))
                and not isinstance(expiry, bool)
            ):
                remaining = expiry - time.time()

                if remaining <= 0:
                    return {
                        "status": "expired",
                        "message": "AEM token has expired",
                        "token": None
                    }

                if remaining < 900:
                    return {
                        "status": "expiring",
                        "message": "Token expires within 15 minutes",
                        "token": token
                    }

                return {
                    "status": "available",
                    "message": "Token available; JWT expiry not reached",
                    "token": token
                }

        except (
            ValueError,
            TypeError,
            UnicodeError,
            OverflowError
        ):
            pass

    return {
        "status": "unknown",
        "message": "Token available; expiry unknown",
        "token": token
    }
