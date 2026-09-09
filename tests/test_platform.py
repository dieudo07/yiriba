"""Tests du back-office éditeur YIRIBA (routes /api/platform).

- Accès strict : réservé à l'éditeur (PLATFORM_ADMIN_EMAILS) — 403 sinon.
- Résumé global, liste des écoles, détail.
- Réinitialisation du mot de passe directeur.
- Gel / dégel d'accès (lecture seule puis restauration).
"""

import pytest
from httpx import AsyncClient

from tests.conftest import platform_admin_token, register_and_login


def _headers(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


class TestPlatformAccess:
    @pytest.mark.asyncio
    async def test_school_admin_forbidden(self, client: AsyncClient):
        """Un directeur d'école ne peut pas accéder au back-office éditeur."""
        school = await register_and_login(client, name="Ecole Pas Editeur")
        res = await client.get("/api/platform/summary", headers=_headers(school["token"]))
        assert res.status_code == 403

    @pytest.mark.asyncio
    async def test_unauthenticated_forbidden(self, client: AsyncClient):
        res = await client.get("/api/platform/summary")
        assert res.status_code == 401


class TestPlatformSummary:
    @pytest.mark.asyncio
    async def test_summary(self, client: AsyncClient):
        editor = await platform_admin_token()
        await register_and_login(client, name="Ecole Summary")

        res = await client.get("/api/platform/summary", headers=_headers(editor))
        assert res.status_code == 200
        data = res.json()
        assert data["total_schools"] >= 1
        assert data["total_users"] >= 1
        assert data["active_subscriptions_amount"] is not None

    @pytest.mark.asyncio
    async def test_list_schools_finds_registered(self, client: AsyncClient):
        editor = await platform_admin_token()
        await register_and_login(client, name="Ecole Recherche")

        res = await client.get("/api/platform/schools", headers=_headers(editor))
        assert res.status_code == 200
        names = [s["name"] for s in res.json()["schools"]]
        assert "Ecole Recherche" in names

        res = await client.get("/api/platform/schools?q=Recherche", headers=_headers(editor))
        assert res.status_code == 200
        assert len(res.json()["schools"]) >= 1
        assert res.json()["schools"][0]["slug"].startswith("ecole-recherche")


class TestPlatformDetail:
    @pytest.mark.asyncio
    async def test_school_detail(self, client: AsyncClient):
        editor = await platform_admin_token()
        school = await register_and_login(client, name="Ecole Detail")

        res = await client.get(
            f"/api/platform/schools/{school['school_id']}", headers=_headers(editor)
        )
        assert res.status_code == 200
        data = res.json()
        assert data["school"]["name"] == "Ecole Detail"
        assert len(data["users"]) >= 1
        assert data["subscriptions"] is not None

        res = await client.get("/api/platform/schools/999999", headers=_headers(editor))
        assert res.status_code == 404


class TestPlatformResetPassword:
    @pytest.mark.asyncio
    async def test_reset_admin_password(self, client: AsyncClient):
        editor = await platform_admin_token()
        school = await register_and_login(client, name="Ecole Reset Mdp")

        res = await client.post(
            f"/api/platform/schools/{school['school_id']}/reset-admin-password",
            headers=_headers(editor),
        )
        assert res.status_code == 200
        data = res.json()
        temp_password = data["temp_password"]
        assert temp_password

        # L'admin peut se reconnecter avec le temp password
        login = await client.post("/api/auth/login", json={
            "email": data["admin_email"],
            "password": temp_password,
        })
        assert login.status_code == 200


class TestPlatformFreeze:
    @pytest.mark.asyncio
    async def test_freeze_blocks_writes_then_unfreeze(self, client: AsyncClient):
        editor = await platform_admin_token()
        school = await register_and_login(client, name="Ecole Gel")
        token = school["token"]
        school_id = school["school_id"]

        student_payload = {
            "first_name": "Eleve", "last_name": "Gel",
            "birth_date": "2015-01-01", "gender": "M",
        }

        # Avant gel : écriture OK
        ok = await client.post("/api/students", json=student_payload, headers=_headers(token))
        assert ok.status_code == 201

        # Gel : plus AUCUN accès (login + sessions coupées, données conservées)
        freeze = await client.post(
            f"/api/platform/schools/{school_id}/freeze", headers=_headers(editor)
        )
        assert freeze.status_code == 200
        assert freeze.json()["is_active"] is False

        blocked = await client.post("/api/students", json=student_payload, headers=_headers(token))
        assert blocked.status_code == 423
        assert "gel" in blocked.json()["detail"].lower()

        # Dégel : accès rétabli
        unfreeze = await client.post(
            f"/api/platform/schools/{school_id}/unfreeze", headers=_headers(editor)
        )
        assert unfreeze.status_code == 200
        assert unfreeze.json()["is_active"] is True

        ok2 = await client.post("/api/students", json=student_payload, headers=_headers(token))
        assert ok2.status_code == 201

    @pytest.mark.asyncio
    async def test_freeze_director_forbidden(self, client: AsyncClient):
        """Le directeur ne peut pas geler sa propre école."""
        school = await register_and_login(client, name="Ecole Pas de Gel")

        res = await client.post(
            f"/api/platform/schools/{school['school_id']}/freeze",
            headers=_headers(school["token"]),
        )
        assert res.status_code == 403


class TestPlatformAudit:
    @pytest.mark.asyncio
    async def test_audit_log_global(self, client: AsyncClient):
        editor = await platform_admin_token()
        school = await register_and_login(client, name="Ecole Audit")

        await client.post(
            f"/api/platform/schools/{school['school_id']}/reset-admin-password",
            headers=_headers(editor),
        )

        res = await client.get("/api/platform/audit", headers=_headers(editor))
        assert res.status_code == 200
        actions = [log["action"] for log in res.json()["logs"]]
        assert "platform.admin_password_reset" in actions
