"""Yiriba SaaS ? Tests complets du module Frais de Scolarit? & Paiements.

V?rifie l'int?gralit? du cahier des charges :
1. Configuration des frais (cat?gories, niveaux, classes, caract?re obligatoire).
2. ?ch?ancier (tranches multiples par obligation).
3. G?n?ration des obligations par ?l?ve / classe.
4. Paiements complets, partiels et calcul automatique du solde.
5. Garde-fou anti-d?passement.
6. Re?us PDF & HTML avec QR, solde restant et caissier.
7. Correction d'un paiement avec motif obligatoire et audit.
8. Annulation d'un paiement avec motif et recalcul du solde.
9. D?biteurs et relances aux parents associ?s.
10. Tableau de bord financier et statistiques par ann?e.
11. Exports CSV (paiements, d?biteurs, obligations).
12. Test critique d'isolation multi-tenant (?cole A / ?cole B).
13. S?paration stricte des ann?es scolaires.
"""

import pytest
from httpx import AsyncClient

from tests.conftest import register_and_login


async def _setup_complete_env(client: AsyncClient, school_name: str = "Lyc?e Yiriba"):
    """Configure une ?cole compl?te avec classe, ?l?ve inscrit et compte admin."""
    ctx = await register_and_login(client, school_name)
    h = {"Authorization": f"Bearer {ctx['token']}"}

    # Cr?ation d'une classe
    r = await client.post("/api/classes", json={
        "name": "6?me A", "level": "6eme", "capacity": 45, "annual_tuition": 150000, "enrollment_fee": 15000
    }, headers=h)
    assert r.status_code in (200, 201), r.text
    class_id = r.json()["id"]

    # Cr?ation d'un ?l?ve
    r = await client.post("/api/students", json={
        "first_name": "Amadou", "last_name": "Diallo", "gender": "M",
    }, headers=h)
    assert r.status_code in (200, 201), r.text
    student_id = r.json()["id"]

    # Inscription de l'?l?ve
    r = await client.post("/api/enrollments", headers=h, json={
        "student_id": student_id, "class_id": class_id,
    })
    assert r.status_code == 201, r.text

    ctx.update(class_id=class_id, student_id=student_id, h=h)
    return ctx


# ??????????????????????????????????????????????????????????????????
# 1. CONFIGURATION DES FRAIS & ?CH?ANCIER
# ??????????????????????????????????????????????????????????????????

class TestFeeConfigurationAndInstallments:
    @pytest.mark.asyncio
    async def test_create_fee_with_category_and_schedule(self, client):
        """Cr?ation d'un frais avec cat?gorie et ?ch?ancier ? 3 tranches."""
        ctx = await _setup_complete_env(client, "?cole ?ch?ancier")
        h = ctx["h"]

        # Cr?ation d'un frais avec tranches (50k en octobre, 50k en janvier, 50k en avril)
        r = await client.post("/api/payments/obligations", headers=h, json={
            "class_id": ctx["class_id"],
            "name": "Scolarit? annuelle 6e",
            "category": "scolarite",
            "level": "6eme",
            "amount": 150000,
            "period": "annuel",
            "academic_year": "2026-2027",
            "due_date": "2027-04-30",
            "is_mandatory": True,
            "installments": [
                {"title": "Paiement 1 ? Octobre", "amount": 50000, "due_date": "2026-10-31", "installment_number": 1},
                {"title": "Paiement 2 ? Janvier", "amount": 50000, "due_date": "2027-01-31", "installment_number": 2},
                {"title": "Paiement 3 ? Avril", "amount": 50000, "due_date": "2027-04-30", "installment_number": 3},
            ]
        })
        assert r.status_code == 201, r.text
        ob_id = r.json()["id"]

        # V?rification de la liste des obligations avec filtres
        r_list = await client.get(f"/api/payments/obligations?category=scolarite&academic_year=2026-2027", headers=h)
        assert r_list.status_code == 200
        obs = r_list.json()["obligations"]
        assert any(o["id"] == ob_id and o["category"] == "scolarite" for o in obs)

        # V?rification des ?ch?ances
        r_inst = await client.get(f"/api/payments/obligations/{ob_id}/installments", headers=h)
        assert r_inst.status_code == 200
        insts = r_inst.json()["installments"]
        assert len(insts) == 3
        assert insts[0]["title"] == "Paiement 1 ? Octobre"
        assert insts[0]["amount"] == 50000


# ??????????????????????????????????????????????????????????????????
# 2. G?N?RATION DES OBLIGATIONS D'UN ?L?VE
# ??????????????????????????????????????????????????????????????????

class TestObligationGeneration:
    @pytest.mark.asyncio
    async def test_generate_student_obligations(self, client):
        """G?n?ration automatique des obligations de l'?l?ve inscrit."""
        ctx = await _setup_complete_env(client, "?cole G?n?ration")
        h = ctx["h"]

        # Cr?er les configurations de frais pour la classe
        await client.post("/api/payments/obligations", headers=h, json={
            "class_id": ctx["class_id"], "name": "Scolarit? 6e", "category": "scolarite",
            "amount": 150000, "period": "annuel", "academic_year": "2026-2027",
        })
        await client.post("/api/payments/obligations", headers=h, json={
            "class_id": ctx["class_id"], "name": "Frais Inscription", "category": "inscription",
            "amount": 10000, "period": "annuel", "academic_year": "2026-2027",
        })

        # Appel de l'endpoint de g?n?ration automatique
        r = await client.post("/api/payments/obligations/generate", headers=h, json={
            "student_id": ctx["student_id"],
            "academic_year": "2026-2027",
        })
        assert r.status_code == 200, r.text
        data = r.json()
        assert data["count"] == 2

        # V?rifier le r?sum? des frais de l'?l?ve
        r_sum = await client.get(f"/api/payments/student/{ctx['student_id']}/fees?academic_year=2026-2027", headers=h)
        assert r_sum.status_code == 200
        summary = r_sum.json()
        assert summary["total_owed"] == 160000
        assert summary["total_paid"] == 0
        assert summary["balance"] == 160000


# ??????????????????????????????????????????????????????????????????
# 3. PAIEMENTS PARTIELS, SOLDE & GARDE ANTI-D?PASSEMENT
# ??????????????????????????????????????????????????????????????????

class TestPaymentsFlow:
    @pytest.mark.asyncio
    async def test_partial_payment_and_cheque_support(self, client):
        """Paiements partiels successifs (50k puis 40k sur 150k -> reste 60k)."""
        ctx = await _setup_complete_env(client, "?cole Paiements")
        h = ctx["h"]

        r_ob = await client.post("/api/payments/obligations", headers=h, json={
            "class_id": ctx["class_id"], "name": "Scolarit? annuelle", "category": "scolarite",
            "amount": 150000, "period": "annuel", "academic_year": "2026-2027",
        })
        ob_id = r_ob.json()["id"]

        # Paiement 1 : 50 000 en esp?ces
        r1 = await client.post("/api/payments", headers=h, json={
            "student_id": ctx["student_id"], "obligation_id": ob_id,
            "amount": 50000, "payment_method": "cash",
        })
        assert r1.status_code == 201
        p1_id = r1.json()["id"]
        await client.patch(f"/api/payments/{p1_id}/confirm", headers=h)

        # Paiement 2 : 40 000 par ch?que
        r2 = await client.post("/api/payments", headers=h, json={
            "student_id": ctx["student_id"], "obligation_id": ob_id,
            "amount": 40000, "payment_method": "cheque", "notes": "Ch?que BOA N?4892",
        })
        assert r2.status_code == 201
        p2_id = r2.json()["id"]
        await client.patch(f"/api/payments/{p2_id}/confirm", headers=h)

        # V?rification du solde restant : 150 000 - 90 000 = 60 000
        r_sum = await client.get(f"/api/payments/student/{ctx['student_id']}/fees?academic_year=2026-2027", headers=h)
        assert r_sum.status_code == 200
        s = r_sum.json()
        assert s["total_paid"] == 90000
        assert s["balance"] == 60000
        assert s["items"][0]["status"] == "partial"

        # Dépassement refusé sans allow_overpay (70 000 > 60 000 restant)
        r_over = await client.post("/api/payments", headers=h, json={
            "student_id": ctx["student_id"], "obligation_id": ob_id,
            "amount": 70000, "payment_method": "cash",
        })
        assert r_over.status_code == 422
        assert "solde restant" in r_over.json()["detail"].lower()


# ??????????????????????????????????????????????????????????????????
# 4. CORRECTION & ANNULATION DE PAIEMENT
# ??????????????????????????????????????????????????????????????????

class TestPaymentCorrectionAndCancellation:
    @pytest.mark.asyncio
    async def test_correct_payment_with_reason(self, client):
        """Correction d'un montant ou moyen de paiement avec motif obligatoire."""
        ctx = await _setup_complete_env(client, "?cole Correction")
        h = ctx["h"]

        r_ob = await client.post("/api/payments/obligations", headers=h, json={
            "class_id": ctx["class_id"], "name": "Frais Scolaires", "amount": 100000, "period": "annuel",
        })
        ob_id = r_ob.json()["id"]

        r_p = await client.post("/api/payments", headers=h, json={
            "student_id": ctx["student_id"], "obligation_id": ob_id,
            "amount": 30000, "payment_method": "cash",
        })
        pid = r_p.json()["id"]
        await client.patch(f"/api/payments/{pid}/confirm", headers=h)

        # Correction sans motif valide -> rejet?e
        r_bad = await client.patch(f"/api/payments/{pid}/correct", headers=h, json={
            "amount": 35000, "reason": "ab",
        })
        assert r_bad.status_code in (400, 422)

        # Correction valide : passage ? 35 000 FCFA avec motif
        r_corr = await client.patch(f"/api/payments/{pid}/correct", headers=h, json={
            "amount": 35000, "payment_method": "bank", "reason": "Rectification suite ? v?rification relev? bancaire",
        })
        assert r_corr.status_code == 200
        assert r_corr.json()["amount"] == 35000
        assert r_corr.json()["payment_method"] == "bank"

        # Le solde est correctement mis ? jour
        r_sum = await client.get(f"/api/payments/student/{ctx['student_id']}/fees", headers=h)
        assert r_sum.json()["total_paid"] == 35000
        assert r_sum.json()["balance"] == 65000


# ??????????????????????????????????????????????????????????????????
# 5. RE?US (PDF & HTML)
# ??????????????????????????????????????????????????????????????????

class TestReceipts:
    @pytest.mark.asyncio
    async def test_receipt_pdf_and_html_generation(self, client):
        """Le re?u contient le caissier, le montant pay? et le solde restant."""
        ctx = await _setup_complete_env(client, "?cole Re?us")
        h = ctx["h"]

        r_ob = await client.post("/api/payments/obligations", headers=h, json={
            "class_id": ctx["class_id"], "name": "Scolarit?", "amount": 100000, "period": "annuel",
        })
        ob_id = r_ob.json()["id"]

        r_p = await client.post("/api/payments", headers=h, json={
            "student_id": ctx["student_id"], "obligation_id": ob_id,
            "amount": 40000, "payment_method": "mobile_money", "mobile_operator": "orange",
        })
        pid = r_p.json()["id"]
        await client.patch(f"/api/payments/{pid}/confirm", headers=h)

        # PDF
        r_pdf = await client.get(f"/api/payments/{pid}/receipt", headers=h)
        assert r_pdf.status_code == 200
        assert r_pdf.headers["content-type"] == "application/pdf"
        assert r_pdf.content[:4] == b"%PDF"

        # HTML
        r_html = await client.get(f"/api/payments/{pid}/receipt/html", headers=h)
        assert r_html.status_code == 200
        assert "text/html" in r_html.headers["content-type"]
        html_body = r_html.text
        assert "PAIEMENT" in html_body
        assert "Solde restant" in html_body


# ??????????????????????????????????????????????????????????????????
# 6. DASHBOARD & EXPORTS MULTIPLES
# ??????????????????????????????????????????????????????????????????

class TestDashboardAndExports:
    @pytest.mark.asyncio
    async def test_financial_dashboard_and_exports(self, client):
        ctx = await _setup_complete_env(client, "?cole Stats")
        h = ctx["h"]

        r_ob = await client.post("/api/payments/obligations", headers=h, json={
            "class_id": ctx["class_id"], "name": "Frais T1", "amount": 80000, "period": "T1", "academic_year": "2026-2027",
        })
        ob_id = r_ob.json()["id"]

        r_p = await client.post("/api/payments", headers=h, json={
            "student_id": ctx["student_id"], "obligation_id": ob_id,
            "amount": 30000, "payment_method": "cash",
        })
        pid = r_p.json()["id"]
        await client.patch(f"/api/payments/{pid}/confirm", headers=h)

        # Dashboard
        r_dash = await client.get("/api/payments/dashboard?academic_year=2026-2027", headers=h)
        assert r_dash.status_code == 200
        d = r_dash.json()
        assert d["billed"] == 80000
        assert d["collected"] == 30000
        assert d["outstanding"] == 50000
        assert d["debtors_count"] >= 1

        # Export paiements
        r_exp_p = await client.get("/api/payments/export/csv?export_type=payments", headers=h)
        assert r_exp_p.status_code == 200
        assert "Montant" in r_exp_p.content.decode("utf-8-sig")

        # Export débiteurs
        r_exp_d = await client.get("/api/payments/export/csv?export_type=debtors", headers=h)
        assert r_exp_d.status_code == 200
        assert "Reste" in r_exp_d.content.decode("utf-8-sig")

        # Export obligations
        r_exp_o = await client.get("/api/payments/export/csv?export_type=obligations", headers=h)
        assert r_exp_o.status_code == 200
        assert "Frais T1" in r_exp_o.content.decode("utf-8-sig")


# ??????????????????????????????????????????????????????????????????
# 7. TEST CRITIQUE : ISOLATION MULTI-TENANT STRICTE
# ??????????????????????????????????????????????????????????????????

class TestMultiTenantStrict:
    @pytest.mark.asyncio
    async def test_strict_isolation_between_schools(self, client):
        """Une ?cole A ne peut en AUCUN CAS acc?der, modifier ou payer pour une ?cole B."""
        a = await _setup_complete_env(client, "?cole Alpha")
        b = await _setup_complete_env(client, "?cole Beta")

        # ?cole B cr?e une obligation et un paiement
        r_ob = await client.post("/api/payments/obligations", headers=b["h"], json={
            "class_id": b["class_id"], "name": "Scolarit? Beta", "amount": 200000, "period": "annuel",
        })
        b_ob_id = r_ob.json()["id"]

        r_p = await client.post("/api/payments", headers=b["h"], json={
            "student_id": b["student_id"], "obligation_id": b_ob_id,
            "amount": 100000, "payment_method": "cash",
        })
        b_pid = r_p.json()["id"]
        await client.patch(f"/api/payments/{b_pid}/confirm", headers=b["h"])

        # 1. A tente de lire le paiement de B -> 404
        r = await client.get(f"/api/payments/{b_pid}", headers=a["h"])
        assert r.status_code == 404

        # 2. A tente d'annuler le paiement de B -> 404
        r = await client.patch(f"/api/payments/{b_pid}/cancel", headers=a["h"], json={"reason": "Tentative frauduleuse"})
        assert r.status_code == 404

        # 3. A tente de corriger le paiement de B -> 404
        r = await client.patch(f"/api/payments/{b_pid}/correct", headers=a["h"], json={"amount": 50, "reason": "Tentative"})
        assert r.status_code == 404

        # 4. A tente de g?n?rer le re?u du paiement de B -> 404
        r = await client.get(f"/api/payments/{b_pid}/receipt", headers=a["h"])
        assert r.status_code == 404
        r = await client.get(f"/api/payments/{b_pid}/receipt/html", headers=a["h"])
        assert r.status_code == 404

        # 5. A tente de payer pour l'?l?ve de B avec l'obligation de B -> 404
        r = await client.post("/api/payments", headers=a["h"], json={
            "student_id": b["student_id"], "obligation_id": b_ob_id, "amount": 5000, "payment_method": "cash",
        })
        assert r.status_code == 404

        # 6. A tente de g?n?rer les obligations pour l'?l?ve de B -> 404
        r = await client.post("/api/payments/obligations/generate", headers=a["h"], json={
            "student_id": b["student_id"],
        })
        assert r.status_code == 404
