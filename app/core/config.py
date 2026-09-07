"""Yiriba SaaS — Configuration centralisée via pydantic-settings.

Aucun secret en dur : tout vient des variables d'environnement.
"""

from enum import Enum
from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class AppEnvironment(str, Enum):
    DEVELOPMENT = "development"
    STAGING = "staging"
    PRODUCTION = "production"

    @classmethod
    def _missing_(cls, value: object):
        """Tolère les variantes et coquilles : 'Production', 'PROD', 'profuction', '' ..."""
        if not isinstance(value, str):
            return None
        v = value.strip().lower()
        aliases = {
            "prod": cls.PRODUCTION,
            "production": cls.PRODUCTION,
            "dev": cls.DEVELOPMENT,
            "developement": cls.DEVELOPMENT,
            "development": cls.DEVELOPMENT,
            "staging": cls.STAGING,
            "stage": cls.STAGING,
            "test": cls.DEVELOPMENT,
        }
        if v in aliases:
            return aliases[v]
        # Correspondance approximative pour les typos (ex. 'profuction')
        import difflib
        match = difflib.get_close_matches(v, list(aliases.keys()), n=1, cutoff=0.6)
        return aliases[match[0]] if match else None


class Settings(BaseSettings):
    """Application settings — loaded from .env or environment variables."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
    )

    # ── Application ───────────────────────────────────────────────
    APP_NAME: str = "Yiriba"
    APP_ENV: AppEnvironment = AppEnvironment.DEVELOPMENT
    APP_DEBUG: bool = True
    APP_SECRET_KEY: str = "change-me-32-char-minimum-random-string"
    APP_PORT: int = 5050

    _DEFAULT_SECRETS: tuple[str, ...] = (
        "change-me-32-char-minimum-random-string",
        "change-me-32-char-minimum-jwt-secret",
        "",
    )

    # ── Database ──────────────────────────────────────────────────
    DATABASE_URL: str = "sqlite+aiosqlite:///./yiriba.db"
    DATABASE_ENCRYPTION_KEY: str = ""

    # ── JWT ───────────────────────────────────────────────────────
    JWT_SECRET_KEY: str = "change-me-32-char-minimum-jwt-secret"
    JWT_ALGORITHM: str = "HS256"
    JWT_ACCESS_TOKEN_EXPIRE_MINUTES: int = 480
    JWT_REFRESH_TOKEN_EXPIRE_DAYS: int = 7

    # ── Rate Limiting ─────────────────────────────────────────────
    RATE_LIMIT_LOGIN: str = "5/minute"
    RATE_LIMIT_API: str = "60/minute"

    # ── Server ──────────────────────────────────────────────────
    SERVER_URL: str = "http://127.0.0.1:5050"

    # ── Uploads ───────────────────────────────────────────────────
    UPLOAD_DIR: str = "./uploads"
    MAX_UPLOAD_SIZE_MB: int = 10

    # ── Mobile Money (PayDunya) ──────────────────────────────────
    PAYDUNYA_PARTNER_TOKEN: str = ""
    PAYDUNYA_APP_TOKEN: str = ""
    PAYDUNYA_MASTER_KEY: str = ""
    PAYDUNYA_MODE: str = "sandbox"

    # ── Google OAuth ──────────────────────────────────────────────
    GOOGLE_CLIENT_ID: str = ""
    GOOGLE_CLIENT_SECRET: str = ""
    GOOGLE_REDIRECT_URI: str = ""  # vide = dérivé automatiquement de l'adresse du navigateur

    # ── Captcha (Cloudflare Turnstile) ────────────────────────────
    TURNSTILE_SITE_KEY: str = ""
    TURNSTILE_SECRET_KEY: str = ""

    # ── Confirmation d'inscription par email ──────────────────────
    # True => le compte reste 'pending' jusqu'au clic sur le lien reçu par email.
    # False => le compte est actif immédiatement (comportement historique).
    REQUIRE_EMAIL_CONFIRMATION: bool = False
    CONFIRMATION_TOKEN_TTL_HOURS: int = 24

    # ── Email ──────────────────────────────────────────────────────
    # EMAIL_PROVIDER = "resend" (API REST, recommandé) ou "smtp".
    # Si aucun fournisseur n'est configuré, les emails sont loggés (dev).
    EMAIL_PROVIDER: str = "smtp"
    RESEND_API_KEY: str = ""
    RESEND_FROM: str = "YIRIBA <onboarding@resend.dev>"
    SMTP_HOST: str = ""
    SMTP_PORT: int = 587
    SMTP_USER: str = ""
    SMTP_PASSWORD: str = ""
    SMTP_FROM: str = "YIRIBA <no-reply@yiriba.app>"
    SMTP_USE_TLS: bool = True

    # ── SMS ───────────────────────────────────────────────────────
    SMS_API_URL: str = ""
    SMS_API_KEY: str = ""
    SMS_SENDER: str = "YIRIBA"

    # ── CORS ──────────────────────────────────────────────────────
    CORS_ORIGINS: str = "*"

    # ── Plateforme ────────────────────────────────────────────────
    # Emails autorisés à gérer le catalogue de forfaits (admin YIRIBA plateforme).
    # Séparés par des virgules. Vide = personne (aucun admin d'école ne peut le faire).
    PLATFORM_ADMIN_EMAILS: str = ""

    # ── Logging ───────────────────────────────────────────────────
    LOG_LEVEL: str = "INFO"

    @property
    def is_production(self) -> bool:
        return self.APP_ENV == AppEnvironment.PRODUCTION

    def validate_production_secrets(self) -> None:
        """Raise if production is running with weak/default secret keys."""
        for name, value in (
            ("APP_SECRET_KEY", self.APP_SECRET_KEY),
            ("JWT_SECRET_KEY", self.JWT_SECRET_KEY),
        ):
            if value in self._DEFAULT_SECRETS or len(value) < 40:
                raise RuntimeError(
                    f"{name} est trop faible pour la production. "
                    f"Définissez une clé aléatoire d'au moins 40 caractères dans .env "
                    f"(ex. `python -c \"import secrets; print(secrets.token_urlsafe(48))\"`)."
                )

    @property
    def cors_origins_list(self) -> list[str]:
        return [o.strip() for o in self.CORS_ORIGINS.split(",") if o.strip()]

    @property
    def platform_admin_emails(self) -> list[str]:
        return [e.strip().lower() for e in self.PLATFORM_ADMIN_EMAILS.split(",") if e.strip()]

    @property
    def smtp_configured(self) -> bool:
        return bool(self.SMTP_HOST.strip())

    @property
    def captcha_enabled(self) -> bool:
        return bool(self.TURNSTILE_SECRET_KEY.strip())

    @property
    def upload_path(self) -> Path:
        path = Path(self.UPLOAD_DIR)
        path.mkdir(parents=True, exist_ok=True)
        return path


@lru_cache
def get_settings() -> Settings:
    """Singleton settings — loaded once, reused everywhere."""
    settings = Settings()
    if settings.is_production:
        settings.validate_production_secrets()
    return settings
