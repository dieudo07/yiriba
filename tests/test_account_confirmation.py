"""Yiriba SaaS — Tests du flux d'inscription : CGU, captcha, confirmation email."""

import uuid
from types import SimpleNamespace


def _register_payload(email: str | None = None, **overrides) -> dict:
    uid = str(uuid.uuid4())[:8]
    payload = {
        "school_name": f"Ecole Confirm {uid}",
        "school_type": "college",
        "school_city": "Ouaga",
        "admin_first_name": "Directeur",
        "admin_last_name": "Test",
        "admin_email": email or f"confirm_{uid}@test.com",
        "admin_phone": f"+226{uid[:8]}",
        "plan_code": "graine",
        "cgv_accepted": True,
    }
    payload.update(overrides)
    return payload


def _confirm_fake_settings() -> SimpleNamespace:
    return SimpleNamespace(
        REQUIRE_EMAIL_CONFIRMATION=True,
        CONFIRMATION_TOKEN_TTL_HOURS=24,
        SERVER_URL="http://testserver",
        is_production=False,
        captcha_enabled=False,
        TURNSTILE_SECRET_KEY="",
    )


async def test_register_requires_cgv(client):
    res = await client.post(
        "/api/auth/register-school", json=_register_payload(cgv_accepted=False)
    )
    assert res.status_code == 400
    assert "conditions" in res.json()["detail"]


async def test_register_rejects_failed_captcha(client, monkeypatch):
    async def fake_verify(token):
        return False

    monkeypatch.setattr("app.routes.auth._verify_turnstile", fake_verify)
    res = await client.post("/api/auth/register-school", json=_register_payload())
    assert res.status_code == 400
    assert "anti-robot" in res.json()["detail"]


async def test_register_accepts_valid_captcha(client, monkeypatch):
    async def fake_verify(token):
        return True

    monkeypatch.setattr("app.routes.auth._verify_turnstile", fake_verify)
    res = await client.post("/api/auth/register-school", json=_register_payload())
    assert res.status_code == 200


async def test_registration_config_endpoint(client):
    res = await client.get("/api/auth/registration-config")
    assert res.status_code == 200
    body = res.json()
    assert body["captcha_provider"] == "turnstile"
    assert "turnstile_site_key" in body
    assert "require_email_confirmation" in body


async def test_confirm_account_flow_with_email_confirmation(client, monkeypatch):
    """Mode confirmation : compte pending -> login refusé -> activation -> login OK."""

    async def fake_send(to_address, subject, html):
        return True

    monkeypatch.setattr(
        "app.services.email_service.send_email",
        fake_send,
    )
    monkeypatch.setattr(
        "app.routes.auth.get_settings",
        lambda: _confirm_fake_settings(),
    )

    email = f"pending_{uuid.uuid4().hex[:8]}@test.com"
    res = await client.post("/api/auth/register-school", json=_register_payload(email=email))
    assert res.status_code == 200
    body = res.json()
    assert body["confirmation_required"] is True
    assert body["confirmation_url"], "confirmation_url doit être exposé hors production"
    assert "temp_password" in body["admin"]

    temp_password = body["admin"]["temp_password"]

    blocked = await client.post(
        "/api/auth/login", json={"email": email, "password": temp_password}
    )
    assert blocked.status_code == 403

    bad = await client.post("/api/auth/confirm-account", json={"token": "nimporte-quoi"})
    assert bad.status_code == 400

    token = body["confirmation_url"].split("token=")[-1]
    confirmed = await client.post("/api/auth/confirm-account", json={"token": token})
    assert confirmed.status_code == 200
    assert "activé" in confirmed.json()["message"].lower()

    ok = await client.post(
        "/api/auth/login", json={"email": email, "password": temp_password}
    )
    assert ok.status_code == 200
    assert "access_token" in ok.json()

    again = await client.post("/api/auth/confirm-account", json={"token": token})
    assert again.status_code == 400


async def test_confirm_account_expired_token(client, monkeypatch, db):
    from datetime import UTC, datetime, timedelta

    from sqlalchemy import select

    from app.models.user import User

    async def fake_send(to_address, subject, html):
        return True

    monkeypatch.setattr(
        "app.services.email_service.send_email",
        fake_send,
    )
    monkeypatch.setattr(
        "app.routes.auth.get_settings",
        lambda: _confirm_fake_settings(),
    )

    email = f"expired_{uuid.uuid4().hex[:8]}@test.com"
    res = await client.post("/api/auth/register-school", json=_register_payload(email=email))
    assert res.status_code == 200

    user = (await db.execute(select(User).where(User.email == email))).scalar_one()
    user.account_confirmation_expires_at = datetime.now(UTC) - timedelta(hours=2)
    await db.commit()

    token = res.json()["confirmation_url"].split("token=")[-1]
    expired = await client.post("/api/auth/confirm-account", json={"token": token})
    assert expired.status_code == 400
