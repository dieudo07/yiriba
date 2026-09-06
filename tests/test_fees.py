"""Yiriba SaaS — Tests module Paiements & Scolarité (fee_service).

Couvre : obligations, paiement partiel/complet, garde anti-dépassement,
annulation avec motif, relances, tableau de bord, export CSV,
isolation multi-tenant et séparation des années scolaires.
"""
import pytest
from httpx import AsyncClient

from tests.conftest import register_and_login  # noqa: F401


# ── Helpers spécifiques finance ─────────────────────────────────


async def _setup_school_with_class_and_student(client: AsyncClient, name: str = "Ecole Fin"):
    """École + classe + élève + obligation de frais. Retourne le contexte."""
    ctx = await register_and_login(client, name)
    h = {"Authorization": f"Bearer {ctx['token']}"}

    r = await client.post("/api/classes", json={"name": "6e A", "level": "6eme", "capacity": 40}, headers=h)
    assert r.status_code in (200, 201), r.text
    class_id = r.json()["id"]

    r = await client.post("/api/students", json={
        "first_name": "Amadou", "last_name": "Testfin", "gender": "M",
    }, headers=h)
    assert r.status_code in (200, 201), r.text
    student_id = r.json()["id"]

    # Inscrire l'élève dans la classe (inscription active)
    r = await client.post("/api/enrollments", headers=h, json={
        "student_id": student_id, "class_id": class_id,
    })
    assert r.status_code == 201, r.text

    r = await client.post("/api/payments/obligations", headers=h, json={
        "class_id": class_id, "name": "Scolarité annuelle", "amount": 150000,
        "period": "annuel", "academic_year": "2026-2027", "due_date": "2027-04-30",
    })
    assert r.status_code == 201, r.text
    obligation_id = r.json()["id"]

    ctx.update(class_id=class_id, student_id=student_id, obligation_id=obligation_id, h=h)
    return ctx


async def _pay_and_confirm(client, h, student_id, obligation_id, amount, **extra):
    r = await client.post("/api/payments", headers=h, json={
        "student_id": student_id, "obligation_id": obligation_id,
        "amount": amount, "payment_method": "cash", **extra,
    })
    assert r.status_code == 201, r.text
    pid = r.json()["id"]
    rc = await client.patch(f"/api/payments/{pid}/confirm", headers=h)
    assert rc.status_code == 200, rc.text
    return pid


# ══════════════════════════════════════════════════════════════════
# OBLIGATIONS & RÉSUMÉ
# ══════════════════════════════════════════════════════════════════


class TestObligations:
    @pytest.mark.asyncio
    async def test_create_and_read_obligation(self, client):
        ctx = await _setup_school_with_class_and_student(client)
        r = await client.get(
            f"/api/payments/student/{ctx['student_id']}/fees", headers=ctx["h"])
        assert r.status_code == 200
        data = r.json()
        assert data["total_owed"] == 150000
        assert data["total_paid"] == 0
        assert data["balance"] == 150000
        assert len(data["items"]) == 1
        assert data["items"][0]["status"] == "unpaid"

    @pytest.mark.asyncio
    async def test_year_separation(self, client):
        """Les obligations d'années différentes ne se mélangent pas."""
        ctx = await _setup_school_with_class_and_student(client, "Ecole An")
        h = ctx["h"]
        # Obligation 2027-2028 sur la même classe
        r = await client.post("/api/payments/obligations", headers=h, json={
            "class_id": ctx["class_id"], "name": "Frais future", "amount": 90000,
            "period": "annuel", "academic_year": "2027-2028",
        })
        assert r.status_code == 201
        # Le résumé sans année voit tout ; en filtrant par année, la séparation est effective
        r = await client.get(
            f"/api/payments/student/{ctx['student_id']}/fees?academic_year=2026-2027", headers=h)
        assert r.json()["total_owed"] == 150000
        r = await client.get(
            f"/api/payments/student/{ctx['student_id']}/fees?academic_year=2027-2028", headers=h)
        assert r.json()["total_owed"] == 90000


# ══════════════════════════════════════════════════════════════════
# PAIEMENTS PARTIELS & GARDE ANTI-DÉPASSEMENT
# ══════════════════════════════════════════════════════════════════


class TestPayments:
    @pytest.mark.asyncio
    async def test_partial_payments_and_balance(self, client):
        ctx = await _setup_school_with_class_and_student(client, "Ecole Part")
        h, sid, oid = ctx["h"], ctx["student_id"], ctx["obligation_id"]

        await _pay_and_confirm(client, h, sid, oid, 50000)
        await _pay_and_confirm(client, h, sid, oid, 40000)

        r = await client.get(f"/api/payments/student/{sid}/fees", headers=h)
        data = r.json()
        assert data["total_paid"] == 90000
        assert data["balance"] == 60000
        assert data["items"][0]["status"] == "partial"

        # Solde à zéro
        await _pay_and_confirm(client, h, sid, oid, 60000)
        r = await client.get(f"/api/payments/student/{sid}/fees", headers=h)
        data = r.json()
        assert data["balance"] == 0
        assert data["items"][0]["status"] == "paid"

    @pytest.mark.asyncio
    async def test_overpay_guard(self, client):
        """Un paiement qui dépasse le dû est refusé sans règle explicite."""
        ctx = await _setup_school_with_class_and_student(client, "Ecole Guard")
        h, sid, oid = ctx["h"], ctx["student_id"], ctx["obligation_id"]

        r = await client.post("/api/payments", headers=h, json={
            "student_id": sid, "obligation_id": oid,
            "amount": 200000, "payment_method": "cash",
        })
        assert r.status_code == 422
        assert "dépasse" in r.json()["detail"].lower()

        # Avec allow_overpay, ça passe
        r = await client.post("/api/payments", headers=h, json={
            "student_id": sid, "obligation_id": oid,
            "amount": 200000, "payment_method": "cash", "allow_overpay": True,
        })
        assert r.status_code == 201

    @pytest.mark.asyncio
    async def test_cancel_with_reason(self, client):
        """Annulation : motif obligatoire, solde recalculé, audit."""
        ctx = await _setup_school_with_class_and_student(client, "Ecole Canc")
        h, sid, oid = ctx["h"], ctx["student_id"], ctx["obligation_id"]
        pid = await _pay_and_confirm(client, h, sid, oid, 50000)

        # Motif trop court → refusé
        r = await client.patch(f"/api/payments/{pid}/cancel", headers=h,
                               json={"reason": "x"})
        assert r.status_code == 422

        r = await client.patch(f"/api/payments/{pid}/cancel", headers=h,
                               json={"reason": "Erreur de saisie double"})
        assert r.status_code == 200
        assert r.json()["status"] == "cancelled"

        # Le solde est recalculé (paiement annulé non compté)
        r = await client.get(f"/api/payments/student/{sid}/fees", headers=h)
        assert r.json()["total_paid"] == 0
        assert r.json()["balance"] == 150000

    @pytest.mark.asyncio
    async def test_receipt_pdf(self, client):
        ctx = await _setup_school_with_class_and_student(client, "Ecole Recu")
        pid = await _pay_and_confirm(
            client, ctx["h"], ctx["student_id"], ctx["obligation_id"], 25000)
        r = await client.get(f"/api/payments/{pid}/receipt", headers=ctx["h"])
        assert r.status_code == 200
        assert r.headers["content-type"] == "application/pdf"
        assert r.content[:4] == b"%PDF"

    @pytest.mark.asyncio
    async def test_dashboard_and_export(self, client):
        ctx = await _setup_school_with_class_and_student(client, "Ecole Dash")
        h, sid, oid = ctx["h"], ctx["student_id"], ctx["obligation_id"]
        await _pay_and_confirm(client, h, sid, oid, 50000)

        r = await client.get("/api/payments/dashboard", headers=h)
        assert r.status_code == 200
        data = r.json()
        assert data["billed"] == 150000
        assert data["collected"] == 50000
        assert data["outstanding"] == 100000

        r = await client.get("/api/payments/export/csv", headers=h)
        assert r.status_code == 200
        body = r.content.decode("utf-8-sig")
        assert "Montant" in body and "50000" in body


# ══════════════════════════════════════════════════════════════════
# RELANCES
# ══════════════════════════════════════════════════════════════════


class TestReminders:
    @pytest.mark.asyncio
    async def test_debtors_and_reminder(self, client):
        ctx = await _setup_school_with_class_and_student(client, "Ecole Rel")
        h, sid = ctx["h"], ctx["student_id"]

        r = await client.get("/api/payments/debtors", headers=h)
        assert r.status_code == 200
        debtors = r.json()["debtors"]
        assert any(d["student_id"] == sid for d in debtors)

        # Relance — aucun parent lié → sent=0 mais pas d'erreur
        r = await client.post("/api/payments/reminders", headers=h,
                              json={"student_ids": [sid]})
        assert r.status_code == 200
        assert r.json()["students_requested"] == 1

        # Élève à jour → pas de relance nécessaire
        await _pay_and_confirm(client, h, sid, ctx["obligation_id"], 150000)
        r = await client.post("/api/payments/reminders", headers=h,
                              json={"student_ids": [sid]})
        assert r.json()["sent"] == 0


# ══════════════════════════════════════════════════════════════════
# ISOLATION MULTI-TENANT (TEST CRITIQUE)
# ══════════════════════════════════════════════════════════════════


class TestMultiTenant:
    @pytest.mark.asyncio
    async def test_school_a_cannot_access_school_b_fees(self, client):
        """École A ne voit ni les obligations ni les paiements de l'école B."""
        a = await _setup_school_with_class_and_student(client, "Ecole Iso A")
        b = await _setup_school_with_class_and_student(client, "Ecole Iso B")

        # Paiement réel chez B
        await _pay_and_confirm(
            client, b["h"], b["student_id"], b["obligation_id"], 70000)

        # A tente de lire les frais de l'élève de B → élève introuvable
        r = await client.get(
            f"/api/payments/student/{b['student_id']}/fees", headers=a["h"])
        assert r.status_code == 404

        # A tente de payer avec l'obligation de B → introuvable
        r = await client.post("/api/payments", headers=a["h"], json={
            "student_id": a["student_id"], "obligation_id": b["obligation_id"],
            "amount": 1000, "payment_method": "cash",
        })
        assert r.status_code == 404

        # A ne voit AUCUN paiement (elle n'en a pas) et B voit le sien
        r = await client.get("/api/payments?per_page=100", headers=a["h"])
        ids_a = {p["id"] for p in r.json()["payments"]}
        r_b = await client.get("/api/payments?per_page=100", headers=b["h"])
        ids_b = {p["id"] for p in r_b.json()["payments"]}
        assert ids_b and not ids_a
        assert not (ids_a & ids_b)

        # Le dashboard de B montre les chiffres de B uniquement
        r = await client.get("/api/payments/dashboard", headers=b["h"])
        assert r.json()["collected"] == 70000
        r = await client.get("/api/payments/dashboard", headers=a["h"])
        assert r.json()["collected"] == 0

    @pytest.mark.asyncio
    async def test_permission_required(self, client):
        """Sans token → 401 sur les routes finance."""
        r = await client.get("/api/payments/debtors")
        assert r.status_code == 401
        r = await client.get("/api/payments/dashboard")
        assert r.status_code == 401
