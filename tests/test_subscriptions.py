"""Tests for YIRIBA subscription limits and plan changes.

Tests couvrent :
- Limites des 3 forfaits (Graine=100, Racine=400, Baobab=illimite)
- Changement de forfait (upgrade + downgrade impossible) — réservé à l'éditeur
- Le directeur d'école ne peut PAS activer/changer son propre forfait (403)
- Historique conserve
- Essai expire = lecture seule
"""

import pytest
from httpx import AsyncClient


def _headers(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


# ── Fixtures ───────────────────────────────────────────────────────


async def _register_school(client: AsyncClient, suffix: str) -> dict:
    """Register a new school and return tokens + school_id."""
    from tests.conftest import register_and_login

    return await register_and_login(
        client,
        name=f"Ecole Sub {suffix}",
    )


async def _register_editor(_client: AsyncClient, suffix: str = "") -> dict:
    """Return a valid editor (YIRIBA platform admin) token."""
    from tests.conftest import platform_admin_token

    return {"token": await platform_admin_token()}


async def _create_students(client: AsyncClient, token: str, count: int) -> int:
    """Create N students, return number successfully created."""
    created = 0
    for i in range(count):
        res = await client.post("/api/students", json={
            "first_name": f"Eleve{i}",
            "last_name": f"Test{i}",
            "birth_date": "2015-01-01",
            "gender": "M",
        }, headers=_headers(token))
        if res.status_code == 201:
            created += 1
    return created


async def _get_school_status(client: AsyncClient, token: str, school_id: int) -> dict:
    """Get subscription status for a school."""
    res = await client.get(f"/api/subscriptions/school/{school_id}", headers=_headers(token))
    assert res.status_code == 200
    return res.json()


# ── Tests Limites ──────────────────────────────────────────────────


class TestSubscriptionLimits:
    """Tests des limites d'eleves par forfait."""

    @pytest.mark.asyncio
    async def test_graine_allows_100_students(self, client: AsyncClient):
        """Graine autorise 100 eleves."""
        school = await _register_school(client, "graine-limit")
        token = school["token"]

        created = await _create_students(client, token, 100)
        assert created == 100

        # 101e eleve refuse
        res = await client.post("/api/students", json={
            "first_name": "Extra", "last_name": "Student",
            "birth_date": "2015-01-01", "gender": "M",
        }, headers=_headers(token))
        assert res.status_code == 403
        assert "Graine" in res.json()["detail"]

    @pytest.mark.asyncio
    async def test_baobab_no_limit(self, client: AsyncClient):
        """Baobab n'a aucune limite."""
        school = await _register_school(client, "baobab-nolimit")
        editor = await _register_editor(client, "baobab")
        token = school["token"]

        # L'editeur passe l'ecole a Baobab
        res = await client.post(
            f"/api/subscriptions/school/{school['school_id']}/change-plan",
            json={"plan_code": "baobab"},
            headers=_headers(editor["token"]),
        )
        assert res.status_code == 200

        # Creer 150 eleves (depasse la limite Graine)
        created = await _create_students(client, token, 150)
        assert created == 150

    @pytest.mark.asyncio
    async def test_expired_school_cannot_create(self, client: AsyncClient):
        """Une ecole expiree ne peut pas creer d'eleves."""
        school = await _register_school(client, "expired-limit")
        token = school["token"]
        school_id = school["school_id"]

        # Expired school via direct DB update using the TEST session factory
        from sqlalchemy import text

        from tests.conftest import test_session_factory

        async with test_session_factory() as session:
            await session.execute(text(
                "UPDATE schools SET subscription_status = 'expired' WHERE id = :id"
            ), {"id": school_id})
            await session.commit()

        res = await client.post("/api/students", json={
            "first_name": "Blocked", "last_name": "Student",
            "birth_date": "2015-01-01", "gender": "M",
        }, headers=_headers(token))
        assert res.status_code == 403
        assert "expire" in res.json()["detail"].lower()

        # Restore
        async with test_session_factory() as session:
            await session.execute(text(
                "UPDATE schools SET subscription_status = 'trial' WHERE id = :id"
            ), {"id": school_id})
            await session.commit()


# ── Tests Changement de forfait ────────────────────────────────────


class TestPlanChange:
    """Tests de changement de forfait — réservé à l'éditeur YIRIBA."""

    @pytest.mark.asyncio
    async def test_trial_to_racine(self, client: AsyncClient):
        """Passage de l'essai Graine a Racine (par l'editeur)."""
        school = await _register_school(client, "trial-to-racine")
        editor = await _register_editor(client)
        token = school["token"]
        school_id = school["school_id"]

        # Creer 5 eleves
        await _create_students(client, token, 5)

        # L'editeur change vers Racine
        res = await client.post(
            f"/api/subscriptions/school/{school_id}/change-plan",
            json={"plan_code": "racine"},
            headers=_headers(editor["token"]),
        )
        assert res.status_code == 200
        data = res.json()
        assert data["new_plan"] == "Racine"
        assert data["status"] == "active"

        # Verifier le statut
        status = await _get_school_status(client, token, school_id)
        assert status["plan"]["code"] == "racine"
        assert status["subscription_status"] == "active"

    @pytest.mark.asyncio
    async def test_trial_to_baobab(self, client: AsyncClient):
        """Passage direct de l'essai a Baobab (par l'editeur)."""
        school = await _register_school(client, "trial-to-baobab")
        editor = await _register_editor(client)
        school_id = school["school_id"]

        res = await client.post(
            f"/api/subscriptions/school/{school_id}/change-plan",
            json={"plan_code": "baobab", "custom_amount": "500000"},
            headers=_headers(editor["token"]),
        )
        assert res.status_code == 200
        assert res.json()["new_plan"] == "Baobab"

    @pytest.mark.asyncio
    async def test_racine_to_baobab(self, client: AsyncClient):
        """Upgrade Racine -> Baobab (par l'editeur)."""
        school = await _register_school(client, "racine-to-baobab")
        editor = await _register_editor(client)
        school_id = school["school_id"]

        # D'abord Racine
        await client.post(
            f"/api/subscriptions/school/{school_id}/change-plan",
            json={"plan_code": "racine"},
            headers=_headers(editor["token"]),
        )

        # Puis Baobab
        res = await client.post(
            f"/api/subscriptions/school/{school_id}/change-plan",
            json={"plan_code": "baobab"},
            headers=_headers(editor["token"]),
        )
        assert res.status_code == 200
        assert res.json()["new_plan"] == "Baobab"

    @pytest.mark.asyncio
    async def test_downgrade_blocked(self, client: AsyncClient):
        """Downgrade impossible si trop d'eleves."""
        school = await _register_school(client, "downgrade-blocked")
        editor = await _register_editor(client)
        token = school["token"]
        school_id = school["school_id"]

        # Passer a Racine
        await client.post(
            f"/api/subscriptions/school/{school_id}/change-plan",
            json={"plan_code": "racine"},
            headers=_headers(editor["token"]),
        )

        # Creer 150 eleves (depasse Graine=100)
        await _create_students(client, token, 150)

        # Tenter downgrade vers Graine — bloque
        res = await client.post(
            f"/api/subscriptions/school/{school_id}/change-plan",
            json={"plan_code": "graine"},
            headers=_headers(editor["token"]),
        )
        assert res.status_code == 400
        assert "Downgrade impossible" in res.json()["detail"]

    @pytest.mark.asyncio
    async def test_history_preserved(self, client: AsyncClient):
        """L'historique des abonnements est conserve."""
        school = await _register_school(client, "history-preserved")
        editor = await _register_editor(client)
        token = school["token"]
        school_id = school["school_id"]

        # L'editeur change 2 fois
        await client.post(
            f"/api/subscriptions/school/{school_id}/change-plan",
            json={"plan_code": "racine"},
            headers=_headers(editor["token"]),
        )
        await client.post(
            f"/api/subscriptions/school/{school_id}/change-plan",
            json={"plan_code": "baobab"},
            headers=_headers(editor["token"]),
        )

        # Verifier l'historique (lecture par l'ecole)
        res = await client.get(
            f"/api/subscriptions/school/{school_id}/history",
            headers=_headers(token),
        )
        assert res.status_code == 200
        subs = res.json()["subscriptions"]
        assert len(subs) >= 2  # trial + racine + baobab

    @pytest.mark.asyncio
    async def test_invalid_plan_code(self, client: AsyncClient):
        """Code de forfait invalide rejete."""
        school = await _register_school(client, "invalid-plan")
        editor = await _register_editor(client)
        school_id = school["school_id"]

        res = await client.post(
            f"/api/subscriptions/school/{school_id}/change-plan",
            json={"plan_code": "premium"},
            headers=_headers(editor["token"]),
        )
        assert res.status_code in (400, 422)

    @pytest.mark.asyncio
    async def test_director_cannot_change_plan(self, client: AsyncClient):
        """Le directeur ne peut PAS changer le plan de sa propre ecole."""
        school_a = await _register_school(client, "no-self-change-a")
        school_b = await _register_school(client, "no-self-change-b")

        # Sur sa propre ecole
        res = await client.post(
            f"/api/subscriptions/school/{school_a['school_id']}/change-plan",
            json={"plan_code": "racine"},
            headers=_headers(school_a["token"]),
        )
        assert res.status_code == 403

        # Sur l'ecole d'un autre
        res = await client.post(
            f"/api/subscriptions/school/{school_b['school_id']}/change-plan",
            json={"plan_code": "racine"},
            headers=_headers(school_a["token"]),
        )
        assert res.status_code == 403

    @pytest.mark.asyncio
    async def test_director_cannot_activate(self, client: AsyncClient):
        """Le directeur ne peut PAS activer/payer sa propre ecole."""
        school = await _register_school(client, "no-self-activate")

        res = await client.post(
            f"/api/subscriptions/school/{school['school_id']}/activate",
            json={"plan_code": "baobab"},
            headers=_headers(school["token"]),
        )
        assert res.status_code == 403

    @pytest.mark.asyncio
    async def test_editor_can_change_any_school(self, client: AsyncClient):
        """L'editeur peut changer le forfait de n'importe quelle ecole."""
        school = await _register_school(client, "editor-any")
        editor = await _register_editor(client)

        res = await client.post(
            f"/api/subscriptions/school/{school['school_id']}/change-plan",
            json={"plan_code": "racine"},
            headers=_headers(editor["token"]),
        )
        assert res.status_code == 200
        assert res.json()["new_plan"] == "Racine"
