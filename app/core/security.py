"""Yiriba SaaS — Security utilities: JWT, bcrypt, rate limiting, validation."""

import re
import secrets
from datetime import UTC, datetime, timedelta
from typing import Any

from jose import JWTError, jwt
from passlib.context import CryptContext

from app.core.config import get_settings

settings = get_settings()

# ── Password Hashing ──────────────────────────────────────────────

pwd_context = CryptContext(
    schemes=["bcrypt"],
    deprecated="auto",
    bcrypt__rounds=12,  # Minimum 12 rounds — OWASP recommendation
)


def hash_password(password: str) -> str:
    """Hash a password with bcrypt."""
    return pwd_context.hash(password)


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """Verify a password against its hash."""
    return pwd_context.verify(plain_password, hashed_password)


# ── JWT Tokens ────────────────────────────────────────────────────


def create_access_token(
    data: dict[str, Any],
    expires_delta: timedelta | None = None,
) -> str:
    """Create a short-lived access token (default: 15 min)."""
    to_encode = data.copy()
    expire = datetime.now(UTC) + (
        expires_delta
        or timedelta(minutes=settings.JWT_ACCESS_TOKEN_EXPIRE_MINUTES)
    )
    to_encode.update({"exp": expire, "type": "access"})
    return jwt.encode(to_encode, settings.JWT_SECRET_KEY, algorithm=settings.JWT_ALGORITHM)


def create_refresh_token(data: dict[str, Any]) -> str:
    """Create a long-lived refresh token (default: 7 days)."""
    to_encode = data.copy()
    expire = datetime.now(UTC) + timedelta(days=settings.JWT_REFRESH_TOKEN_EXPIRE_DAYS)
    to_encode.update({"exp": expire, "type": "refresh"})
    return jwt.encode(to_encode, settings.JWT_SECRET_KEY, algorithm=settings.JWT_ALGORITHM)


def decode_token(token: str) -> dict[str, Any] | None:
    """Decode and validate a JWT token. Returns None on failure."""
    try:
        payload = jwt.decode(
            token,
            settings.JWT_SECRET_KEY,
            algorithms=[settings.JWT_ALGORITHM],
        )
        return payload
    except JWTError:
        return None


# ── Password Validation ───────────────────────────────────────────


def validate_password(password: str) -> tuple[bool, str]:
    """Validate password complexity. Returns (is_valid, error_message)."""
    if len(password) < 8:
        return False, "Le mot de passe doit contenir au moins 8 caractères"
    if not re.search(r"[A-Z]", password):
        return False, "Le mot de passe doit contenir au moins une majuscule"
    if not re.search(r"[a-z]", password):
        return False, "Le mot de passe doit contenir au moins une minuscule"
    if not re.search(r"\d", password):
        return False, "Le mot de passe doit contenir au moins un chiffre"
    return True, ""


# ── Confirmation Token ────────────────────────────────────────────


def generate_confirmation_token() -> str:
    """Generate a cryptographically secure token for email confirmation."""
    return secrets.token_urlsafe(48)


# ── Input Validation ──────────────────────────────────────────────


def validate_grade(value: float) -> tuple[bool, str]:
    """Validate a grade value (0 to max, usually 20)."""
    if value < 0:
        return False, "La note ne peut pas être négative"
    if value > 100:
        return False, "La note ne peut pas dépasser 100"
    return True, ""


def validate_amount(value: float) -> tuple[bool, str]:
    """Validate a monetary amount."""
    if value <= 0:
        return False, "Le montant doit être supérieur à 0"
    if value > 10_000_000:
        return False, "Le montant est trop élevé"
    return True, ""


def validate_date(date_str: str) -> tuple[bool, str]:
    """Validate a date string (YYYY-MM-DD)."""
    try:
        from datetime import date

        d = date.fromisoformat(date_str)
        if d > date.today():
            return False, "La date ne peut pas être dans le futur"
        if d.year < 1900:
            return False, "L'année est trop ancienne"
        return True, ""
    except ValueError:
        return False, "Format de date invalide (attendu : AAAA-MM-JJ)"


# ── Secure Image Upload ───────────────────────────────────────────


def validate_image_upload(
    content: bytes,
    filename: str | None,
    content_type: str | None,
    allowed_ext: set[str] | None = None,
) -> str:
    """Validate an uploaded image and return the safe extension.

    Vérifie la signature réelle des octets (jamais uniquement le
    Content-Type fourni par le client) et retourne une extension
    whitelistée. Lève ValueError si le fichier n'est pas une image
    connue ou si son extension n'est pas autorisée.
    """
    allowed_ext = allowed_ext or {"jpg", "png", "gif", "webp"}

    if not content:
        raise ValueError("Fichier vide")

    ext_by_signature: list[tuple[bytes, str]] = [
        (b"\xff\xd8\xff", "jpg"),
        (b"\x89PNG\r\n\x1a\n", "png"),
        (b"GIF87a", "gif"),
        (b"GIF89a", "gif"),
        (b"RIFF", "webp"),
    ]

    ext = ""
    for signature, sig_ext in ext_by_signature:
        if content.startswith(signature):
            if sig_ext == "webp" and len(content) >= 12:
                if content[8:12] != b"WEBP":
                    continue
            if sig_ext in allowed_ext:
                ext = sig_ext
            break

    if not ext:
        raise ValueError("Fichier non reconnu comme image autorisée")

    # Cohérence avec le nom de fichier reçu (facultatif, forme de confirmation)
    declared = (filename or "").lower().rsplit(".", 1)[-1]
    if declared in ("jpg", "jpeg", "png", "gif", "webp"):
        if declared == "jpeg":
            declared = "jpg"
        if ext != declared:
            raise ValueError("L'extension du fichier ne correspond pas à son contenu")

    return ext
