"""Yiriba SaaS — Signatures HMAC pour les QR de vérification des documents.

Source de vérité du calcul des jetons. Utilisée par pdf_service.py (génération
du QR) et routes/verify.py (vérification) pour que les deux côtés concordent.

- Bulletin : le jeton lie l'identité (école/élève/classe/période/année) ET les
  valeurs figées (moyenne, rang, effectif) → un document modifié ne passe pas.
- Reçu : le jeton lie l'école au paiement (même schéma que l'ancien n° de reçu).
"""

import hashlib
import hmac

from app.core.config import get_settings


def _sign(payload: str) -> str:
    _cfg = get_settings()
    secret = _cfg.APP_SECRET_KEY.encode()
    return hmac.new(secret, payload.encode(), hashlib.sha256).hexdigest()[:32]


def bulletin_payload(
    school_id: int,
    student_id: int,
    class_id: int,
    period: str,
    academic_year: str,
    display_average: float,
    rank: int,
    effectif: int,
) -> str:
    """Payload canonique couvrant l'identité + les valeurs figées du bulletin."""
    return (f"bulletin:{school_id}:{student_id}:{class_id}:{period}:{academic_year}"
            f":{display_average:.2f}:{rank}:{effectif}")


def bulletin_signature(
    school_id: int,
    student_id: int,
    class_id: int,
    period: str,
    academic_year: str,
    display_average: float,
    rank: int,
    effectif: int,
) -> str:
    return _sign(bulletin_payload(
        school_id, student_id, class_id, period, academic_year,
        display_average, rank, effectif,
    ))


def verify_bulletin_signature(
    signature: str,
    school_id: int,
    student_id: int,
    class_id: int,
    period: str,
    academic_year: str,
    display_average: float,
    rank: int,
    effectif: int,
) -> bool:
    if not signature:
        return False
    expected = bulletin_signature(
        school_id, student_id, class_id, period, academic_year,
        display_average, rank, effectif,
    )
    return hmac.compare_digest(expected, signature)


def receipt_payload(school_id: int, payment_id: int) -> str:
    return f"{school_id}:{payment_id}"


def receipt_signature(school_id: int, payment_id: int) -> str:
    """Jeton HMAC stable du reçu (inversible par calcul, pas par la base)."""
    return _sign(receipt_payload(school_id, payment_id))


def verify_receipt_signature(token: str, school_id: int, payment_id: int) -> bool:
    if not token:
        return False
    expected = receipt_signature(school_id, payment_id)
    return hmac.compare_digest(expected, token)
