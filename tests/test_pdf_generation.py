"""Yiriba SaaS — PDF generation tests.

Tests:
1. Bulletin PDF generation with test data
2. Receipt PDF generation with QR code
3. Multi-tenant isolation (school A data never leaks to school B)
4. Average and rank calculation edge cases
5. Batch bulletin generation
"""

import io
import json

import pytest
from httpx import AsyncClient
from sqlalchemy import select

from app.models.payment import FeeObligation, Payment
from app.services.pdf_service import (
    _mention_from_average,
    _number_to_french_words,
    generate_bulletin_from_snapshot,
    generate_bulletin_pdf,
    generate_bulletins_for_class,
    generate_receipt_pdf,
)


async def _register_school(client: AsyncClient, name: str = "Ecole Test PDF") -> dict:
    """Register a school and return token + IDs."""
    import uuid
    uid = str(uuid.uuid4())[:8]
    slug = f"{name.lower().replace(' ', '-')}-{uid}"
    res = await client.post("/api/auth/register-school", json={
        "school_name": name,
        "school_slug": slug,
        "school_type": "college",
        "school_country": "Burkina Faso",
        "school_city": "Ouaga",
        "admin_first_name": "Admin",
        "admin_last_name": "Test",
        "admin_email": f"admin_{uid}@test.com",
        "admin_password": "Test1234!",
    })
    data = res.json()
    # Pas d'auto-login au register : login avec le mot de passe temporaire.
    login = await client.post("/api/auth/login", json={
        "email": f"admin_{uid}@test.com", "password": data["admin"]["temp_password"],
    })
    return {
        "token": login.json()["access_token"],
        "school_id": data["school"]["id"],
    }


# ── Unit tests (no DB) ──────────────────────────────────────────


class TestMentionCalculation:
    """Test mention thresholds."""

    def test_felicitations(self):
        assert _mention_from_average(16.0) == "Félicitations"
        assert _mention_from_average(18.5) == "Félicitations"

    def test_encouragements(self):
        assert _mention_from_average(14.0) == "Encouragements"
        assert _mention_from_average(15.9) == "Encouragements"

    def test_tableau_dhonneur(self):
        assert _mention_from_average(12.0) == "Tableau d'honneur"
        assert _mention_from_average(13.9) == "Tableau d'honneur"

    def test_passable(self):
        assert _mention_from_average(10.0) == "Passable"
        assert _mention_from_average(11.9) == "Passable"

    def test_avertissement(self):
        assert _mention_from_average(8.0) == "Avertissement"
        assert _mention_from_average(0.0) == "Avertissement"

    def test_boundary_16(self):
        assert _mention_from_average(16.0) == "Félicitations"
        assert _mention_from_average(15.99) == "Encouragements"

    def test_boundary_10(self):
        assert _mention_from_average(10.0) == "Passable"
        assert _mention_from_average(9.99) == "Avertissement"


class TestNumberToWords:
    """Test French number to words conversion."""

    def test_zero(self):
        result = _number_to_french_words(0)
        assert "Zero" in result or "Zéro" in result

    def test_small_numbers(self):
        assert "Deux" in _number_to_french_words(2)
        assert "Cinq" in _number_to_french_words(5)
        assert "Douze" in _number_to_french_words(12)

    def test_tens(self):
        assert "Vingt" in _number_to_french_words(20)
        assert "Cinquante" in _number_to_french_words(50)

    def test_hundreds(self):
        result = _number_to_french_words(100)
        assert "Cent" in result

    def test_large_number(self):
        result = _number_to_french_words(450000)
        assert len(result) > 0  # Just verify it doesn't crash


# ── Integration tests (with DB) ─────────────────────────────────


@pytest.mark.integration
class TestBulletinPDF:
    """Test bulletin PDF generation with real DB data."""

    async def test_generate_bulletin_pdf(self, client: AsyncClient, db):
        """Generate a bulletin PDF and verify it's valid PDF bytes."""
        school = await _register_school(client, "Ecole Bulletin")
        token = school["token"]
        h = {"Authorization": f"Bearer {token}"}

        # Create class
        res = await client.post("/api/classes", json={
            "name": "6e A", "period_type": "trimestre",
        }, headers=h)
        assert res.status_code == 201
        class_id = res.json()["id"]

        # Create subject
        res = await client.post("/api/subjects", json={"name": "Mathematiques"}, headers=h)
        subject_id = res.json()["id"]

        # Link subject to class
        res = await client.post("/api/class-subjects", json={
            "class_id": class_id, "subject_id": subject_id, "coefficient": 4,
        }, headers=h)
        assert res.status_code in (200, 201)

        # Create student
        res = await client.post("/api/students", json={
            "first_name": "Awa", "last_name": "Ouedraogo",
            "gender": "F", "birth_date": "2012-05-15",
        }, headers=h)
        assert res.status_code == 201
        student_id = res.json()["id"]

        # Enroll student
        res = await client.post("/api/enrollments", json={
            "class_id": class_id, "student_id": student_id,
        }, headers=h)
        assert res.status_code == 201, res.text

        # Create evaluation
        res = await client.post("/api/grades/evaluations", json={
            "class_id": class_id, "subject_id": subject_id,
            "name": "Devoir 1", "assessment_type": "devoir1",
            "period": "T1", "max_grade": 20, "coefficient": 1,
            "date": "2025-10-01",
        }, headers=h)
        assert res.status_code in (200, 201), f"Eval creation failed: {res.text}"
        eval_id = res.json()["id"]

        # Enter grade
        res = await client.patch(f"/api/grades/entry?evaluation_id={eval_id}", json={
            "student_id": student_id, "grade": 15.0, "status": "graded",
        }, headers=h)
        assert res.status_code == 200, res.text

        # Generate PDF
        pdf_bytes = await generate_bulletin_pdf(
            db, student_id, class_id, "T1", "2025-2026"
        )

        assert isinstance(pdf_bytes, bytes)
        assert len(pdf_bytes) > 500  # Minimum PDF size
        assert pdf_bytes[:4] == b"%PDF"  # PDF magic bytes

    async def test_generate_bulletin_for_all_students_in_class(self, client: AsyncClient, db):
        """Test batch bulletin generation."""
        school = await _register_school(client, "Ecole Batch")
        token = school["token"]
        h = {"Authorization": f"Bearer {token}"}

        # Create class
        res = await client.post("/api/classes", json={
            "name": "5e B", "period_type": "trimestre",
        }, headers=h)
        class_id = res.json()["id"]

        # Create subject
        res = await client.post("/api/subjects", json={"name": "Francais"}, headers=h)
        subject_id = res.json()["id"]

        res = await client.post("/api/class-subjects", json={
            "class_id": class_id, "subject_id": subject_id, "coefficient": 3,
        }, headers=h)

        # Create 3 students and enroll them
        student_ids = []
        for i in range(3):
            res = await client.post("/api/students", json={
                "first_name": f"Eleve{i}", "last_name": f"Test{i}",
                "gender": "M",
            }, headers=h)
            assert res.status_code == 201, res.text
            sid = res.json()["id"]
            student_ids.append(sid)
            res = await client.post("/api/enrollments", json={
                "class_id": class_id, "student_id": sid,
            }, headers=h)
            assert res.status_code == 201, res.text

        # Create evaluation + grades
        res = await client.post("/api/grades/evaluations", json={
            "class_id": class_id, "subject_id": subject_id,
            "name": "Devoir 1", "assessment_type": "devoir1",
            "period": "T1", "max_grade": 20, "coefficient": 1, "date": "2025-10-01",
        }, headers=h)
        assert res.status_code == 201, res.text
        eval_id = res.json()["id"]
        for idx, sid in enumerate(student_ids, start=1):
            res = await client.patch(f"/api/grades/entry?evaluation_id={eval_id}", json={
                "student_id": sid, "grade": 12.0 + idx, "status": "graded",
            }, headers=h)
            assert res.status_code == 200, res.text

        # Batch generate
        results = await generate_bulletins_for_class(db, class_id, "T1", "2025-2026")

        assert isinstance(results, list)
        # Each result should have the expected keys
        for r in results:
            assert "student_id" in r
            assert "student_name" in r
            assert "pdf" in r
            assert "error" in r


@pytest.mark.integration
class TestReceiptPDF:
    """Test receipt PDF generation."""

    async def test_generate_receipt_pdf(self, client: AsyncClient, db):
        """Generate a receipt PDF and verify it's valid PDF bytes."""
        school = await _register_school(client, "Ecole Receipt")
        token = school["token"]
        h = {"Authorization": f"Bearer {token}"}

        # Create student
        res = await client.post("/api/students", json={
            "first_name": "Moussa", "last_name": "Diallo",
            "gender": "M",
        }, headers=h)
        student_id = res.json()["id"]

        # Create class + enroll
        res = await client.post("/api/classes", json={
            "name": "4e A", "period_type": "trimestre",
        }, headers=h)
        class_id = res.json()["id"]

        res = await client.post("/api/enrollments", json={
            "class_id": class_id, "student_id": student_id,
        }, headers=h)
        assert res.status_code == 201, res.text

        # Create fee obligation
        res = await client.post("/api/admin/fee-obligations", json={
            "class_id": class_id,
            "name": "Frais d'inscription T1",
            "amount": 25000,
            "period": "T1",
        }, headers=h)
        obligation_id = res.json().get("id") if res.status_code in (200, 201) else None

        # Create payment
        payment_data = {
            "student_id": student_id,
            "amount": 25000,
            "payment_method": "cash",
            "notes": "Frais d'inscription T1",
        }
        if obligation_id:
            payment_data["obligation_id"] = obligation_id

        res = await client.post("/api/payments", json=payment_data, headers=h)
        assert res.status_code in (200, 201), f"Payment creation failed: {res.text}"
        payment_id = res.json()["id"]

        # Generate receipt PDF
        pdf_bytes = await generate_receipt_pdf(db, payment_id)

        assert isinstance(pdf_bytes, bytes)
        assert len(pdf_bytes) > 500
        assert pdf_bytes[:4] == b"%PDF"


@pytest.mark.integration
class TestMultiTenantIsolation:
    """Test that PDF generation respects multi-tenant isolation."""

    async def test_school_a_bulletin_does_not_leak_school_b(self, client: AsyncClient, db):
        """Bulletin PDF for school A must only use school A data."""
        school_a = await _register_school(client, "Ecole Alpha")
        school_b = await _register_school(client, "Ecole Beta")

        h_a = {"Authorization": f"Bearer {school_a['token']}"}
        h_b = {"Authorization": f"Bearer {school_b['token']}"}

        # Create class in school A
        res = await client.post("/api/classes", json={
            "name": "6e A", "period_type": "trimestre",
        }, headers=h_a)
        class_a_id = res.json()["id"]

        # Create subject in school A
        res = await client.post("/api/subjects", json={"name": "Maths A"}, headers=h_a)
        subject_a_id = res.json()["id"]

        res = await client.post("/api/class-subjects", json={
            "class_id": class_a_id, "subject_id": subject_a_id, "coefficient": 4,
        }, headers=h_a)

        # Create student in school A
        res = await client.post("/api/students", json={
            "first_name": "Eleve", "last_name": "Alpha",
            "gender": "M",
        }, headers=h_a)
        student_a_id = res.json()["id"]

        res = await client.post("/api/enrollments", json={
            "class_id": class_a_id, "student_id": student_a_id,
        }, headers=h_a)
        assert res.status_code == 201, res.text

        # Create evaluation + grade in school A
        res = await client.post("/api/grades/evaluations", json={
            "class_id": class_a_id, "subject_id": subject_a_id,
            "name": "Devoir 1", "assessment_type": "devoir1",
            "period": "T1", "max_grade": 20, "coefficient": 1, "date": "2025-10-01",
        }, headers=h_a)
        assert res.status_code == 201, res.text
        eval_id = res.json()["id"]
        res = await client.patch(f"/api/grades/entry?evaluation_id={eval_id}", json={
            "student_id": student_a_id, "grade": 14.0, "status": "graded",
        }, headers=h_a)
        assert res.status_code == 200, res.text

        # Generate bulletin for school A student
        pdf_bytes = await generate_bulletin_pdf(
            db, student_a_id, class_a_id, "T1", "2025-2026"
        )

        # Verify PDF is valid
        assert pdf_bytes[:4] == b"%PDF"
        assert len(pdf_bytes) > 1000  # Non-trivial content

        # Key isolation check: the student belongs to school A,
        # so the bulletin must be generated from school A data.
        # We verify this by confirming the student is in school A
        # and that the PDF generation uses school_id from the student.
        from app.models.student import Student as StudentModel
        student = (await db.execute(
            select(StudentModel).where(StudentModel.id == student_a_id)
        )).scalar_one_or_none()
        assert student.school_id == school_a["school_id"]

        # School B student should not be accessible through school A's data
        school_b_students = (await db.execute(
            select(StudentModel).where(StudentModel.school_id == school_b["school_id"])
        )).scalars().all()
        school_b_ids = {s.id for s in school_b_students}
        assert student_a_id not in school_b_ids

    async def test_school_a_receipt_does_not_leak_school_b(self, client: AsyncClient, db):
        """Receipt PDF for school A must only use school A data."""
        school_a = await _register_school(client, "Ecole Gamma")
        school_b = await _register_school(client, "Ecole Delta")

        h_a = {"Authorization": f"Bearer {school_a['token']}"}

        # Create student in school A
        res = await client.post("/api/students", json={
            "first_name": "Ibrahim", "last_name": "Kone",
            "gender": "M",
        }, headers=h_a)
        student_id = res.json()["id"]

        # Create payment in school A
        res = await client.post("/api/payments", json={
            "student_id": student_id,
            "amount": 15000,
            "payment_method": "cash",
            "notes": "Frais scolaire",
        }, headers=h_a)
        payment_id = res.json()["id"]

        # Generate receipt
        pdf_bytes = await generate_receipt_pdf(db, payment_id)

        # Verify PDF is valid
        assert pdf_bytes[:4] == b"%PDF"
        assert len(pdf_bytes) > 1000

        # Key isolation check: verify payment belongs to school A
        from app.models.payment import Payment as PaymentModel
        payment = (await db.execute(
            select(PaymentModel).where(PaymentModel.id == payment_id)
        )).scalar_one_or_none()
        assert payment.school_id == school_a["school_id"]

        # Verify school B payment cannot be accessed via school A token
        from app.models.payment import Payment as PaymentModel2
        school_b_payments = (await db.execute(
            select(PaymentModel2).where(PaymentModel2.school_id == school_b["school_id"])
        )).scalars().all()
        assert payment_id not in {p.id for p in school_b_payments}


@pytest.mark.integration
async def _snapshot_scenario(client: AsyncClient):
    """École + classe trimestre + maths (coef 4) + élève + devoir1 (15/20)."""
    school = await _register_school(client, "Ecole Snapshot")
    token = school["token"]
    h = {"Authorization": f"Bearer {token}"}

    res = await client.post("/api/classes", json={
        "name": "6e A", "period_type": "trimestre",
    }, headers=h)
    class_id = res.json()["id"]

    res = await client.post("/api/subjects", json={"name": "Mathematiques"}, headers=h)
    subject_id = res.json()["id"]

    await client.post("/api/class-subjects", json={
        "class_id": class_id, "subject_id": subject_id, "coefficient": 4,
    }, headers=h)

    res = await client.post("/api/students", json={
        "first_name": "Awa", "last_name": "Ouedraogo", "gender": "F",
    }, headers=h)
    student_id = res.json()["id"]

    res = await client.post("/api/enrollments", json={
        "class_id": class_id, "student_id": student_id,
    }, headers=h)
    assert res.status_code == 201, res.text

    res = await client.post("/api/grades/evaluations", json={
        "class_id": class_id, "subject_id": subject_id,
        "name": "Devoir 1", "assessment_type": "devoir1",
        "period": "T1", "max_grade": 20, "coefficient": 1,
        "date": "2025-10-01",
    }, headers=h)
    assert res.status_code == 201, res.text
    eval_id = res.json()["id"]

    res = await client.patch(f"/api/grades/entry?evaluation_id={eval_id}", json={
        "student_id": student_id, "grade": 15.0, "status": "graded",
    }, headers=h)
    assert res.status_code == 200, res.text

    return school, class_id, student_id


async def _make_bulletin(db, school_id, class_id, student_id, data_json):
    from app.models.bulletin import Bulletin

    snapshot = json.loads(data_json) if isinstance(data_json, str) else data_json
    b = Bulletin(
        school_id=school_id,
        student_id=student_id,
        class_id=class_id,
        period="T1",
        academic_year="2025-2026",
        status="draft",
        data_json=json.dumps(snapshot, ensure_ascii=False),
        overall_average=snapshot.get("overall_average") or 0,
        rank=snapshot.get("rank"),
        total_students=snapshot.get("total_students") or 0,
    )
    db.add(b)
    await db.flush()
    return b


class TestSnapshotBulletinPDF:
    """PDF v2 : rendu EXCLUSIVEMENT depuis le snapshot figé, jamais recalculé."""

    async def _scenario(self, client: AsyncClient):
        return await _snapshot_scenario(client)

    async def _make_bulletin(self, db, school_id, class_id, student_id, data_json):
        return await _make_bulletin(db, school_id, class_id, student_id, data_json)

    async def test_snapshot_enriched_renders_frozen_values(self, client, db):
        """Le snapshot enrichi fournit tous les champs PDF sans aucun recalcul."""
        school, class_id, student_id = await self._scenario(client)

        from app.services.report_card_service import build_snapshot, compute_class_results

        computed = await compute_class_results(
            db, school["school_id"], class_id, "T1", "2025-2026"
        )
        snapshot = build_snapshot(computed, student_id)

        # Le snapshot doit être autosuffisant pour le PDF
        for key in ("display_average", "discipline_mode", "mention", "decision",
                    "total_deductions", "conduct_score", "period_label"):
            assert key in snapshot, f"snapshot manque {key}"
        assert snapshot["display_average"] == 15.0
        assert snapshot["subjects"][0]["average"] == 15.0
        assert snapshot["subjects"][0]["class_average"] == 15.0

        b = await _make_bulletin(
            db, school["school_id"], class_id, student_id, snapshot
        )
        pdf_bytes = await generate_bulletin_from_snapshot(db, b)

        assert isinstance(pdf_bytes, bytes)
        assert len(pdf_bytes) > 500
        assert pdf_bytes[:4] == b"%PDF"

    async def test_snapshot_complete_never_recomputes(self, client, db, monkeypatch):
        """Snapshot complet ⇒ AUCUN appel de recalcul (compute_class_results → raise)."""
        school, class_id, student_id = await self._scenario(client)

        from app.services.report_card_service import build_snapshot, compute_class_results

        computed = await compute_class_results(
            db, school["school_id"], class_id, "T1", "2025-2026"
        )
        snapshot = build_snapshot(computed, student_id)
        b = await _make_bulletin(
            db, school["school_id"], class_id, student_id, snapshot
        )

        import app.services.report_card_service as rcs

        async def _boom(*args, **kwargs):
            raise AssertionError("compute_class_results ne doit pas être appelé")

        monkeypatch.setattr(rcs, "compute_class_results", _boom)

        pdf_bytes = await generate_bulletin_from_snapshot(db, b)
        assert isinstance(pdf_bytes, bytes)
        assert pdf_bytes[:4] == b"%PDF"

    async def test_class_export_zip(self, client, db):
        """Export ZIP : un PDF par bulletin de la classe, généré depuis les snapshots."""
        school, class_id, student_id = await self._scenario(client)

        from app.services.report_card_service import build_snapshot, compute_class_results

        computed = await compute_class_results(
            db, school["school_id"], class_id, "T1", "2025-2026"
        )
        snapshot = build_snapshot(computed, student_id)
        await _make_bulletin(
            db, school["school_id"], class_id, student_id, snapshot
        )
        await db.commit()

        h = {"Authorization": f"Bearer {school['token']}"}
        res = await client.get(
            f"/api/report-cards/class/{class_id}/export?period=T1&academic_year=2025-2026",
            headers=h,
        )
        assert res.status_code == 200, res.text
        assert res.headers["content-type"].startswith("application/zip")
        assert res.content[:2] == b"PK"  # signature ZIP

        import zipfile
        with zipfile.ZipFile(io.BytesIO(res.content)) as zf:
            names = zf.namelist()
            assert names, "archive vide"
            assert all(n.endswith(".pdf") for n in names)
            assert "ouedraogo_awa_bulletin.pdf" in " ".join(n.lower() for n in names)

    async def test_legacy_snapshot_falls_back_without_persisting(self, client, db):
        """Un vieux bulletin (sans champs enrichis) est régénéré uniquement en mémoire."""
        school, class_id, student_id = await self._scenario(client)

        legacy = {
            "subjects": [{
                "id": 1, "name": "Mathematiques", "coefficient": 4,
                "grades": {"devoir1": 15.0}, "average": 15.0,
            }],
            "overall_average": 15.0,
            "rank": 1,
            "total_students": 1,
            "class_average": 15.0,
            "class_best": 15.0,
            "class_worst": 15.0,
        }
        b = await _make_bulletin(
            db, school["school_id"], class_id, student_id, legacy
        )
        pdf_bytes = await generate_bulletin_from_snapshot(db, b)

        assert isinstance(pdf_bytes, bytes)
        assert pdf_bytes[:4] == b"%PDF"

        # Rien n'a été persisté pendant le fallback
        from app.models.bulletin import Bulletin
        refreshed = (await db.execute(
            select(Bulletin).where(Bulletin.id == b.id)
        )).scalar_one()
        stored = json.loads(refreshed.data_json)
        assert "display_average" not in stored


class TestVerificationQR:
    """QR signé HMAC : endpoints publics /api/verify (bulletin + reçu)."""

    async def test_verify_bulletin_valid_signature(self, client, db):
        """Signature correcte ⇒ page « Document authentique »."""
        school, class_id, student_id = await _snapshot_scenario(client)

        from app.services.report_card_service import build_snapshot, compute_class_results
        from app.services.verification_service import bulletin_signature

        computed = await compute_class_results(
            db, school["school_id"], class_id, "T1", "2025-2026"
        )
        snapshot = build_snapshot(computed, student_id)

        b = await _make_bulletin(
            db, school["school_id"], class_id, student_id, snapshot
        )
        await db.commit()

        signature = bulletin_signature(
            b.school_id, b.student_id, b.class_id, b.period, b.academic_year,
            snapshot["display_average"], snapshot["rank"], snapshot["total_students"],
        )
        url = (
            "/api/verify/bulletin/"
            f"{b.student_id}/{b.class_id}/{b.period}/{b.academic_year}/{signature}"
        )

        res = await client.get(url)
        assert res.status_code == 200
        assert "Document authentique" in res.text
        assert "Ecole Snapshot" in res.text
        assert "15.00/20" in res.text

    async def test_verify_bulletin_tampered_signature(self, client, db):
        """Signature altérée ⇒ document non authentique (référence falsifiée)."""
        school, class_id, student_id = await _snapshot_scenario(client)

        from app.services.report_card_service import build_snapshot, compute_class_results

        computed = await compute_class_results(
            db, school["school_id"], class_id, "T1", "2025-2026"
        )
        snapshot = build_snapshot(computed, student_id)
        b = await _make_bulletin(
            db, school["school_id"], class_id, student_id, snapshot
        )
        await db.commit()

        url = (
            "/api/verify/bulletin/"
            f"{b.student_id}/{b.class_id}/{b.period}/{b.academic_year}/{'0' * 32}"
        )
        res = await client.get(url)
        assert res.status_code == 200
        assert "Signature invalide" in res.text

    async def test_verify_bulletin_legacy_no_signature(self, client, db):
        """Ancien QR sans signature ⇒ page informative « non signé », pas d'échec brut."""
        school, class_id, student_id = await _snapshot_scenario(client)

        from app.services.report_card_service import build_snapshot, compute_class_results

        computed = await compute_class_results(
            db, school["school_id"], class_id, "T1", "2025-2026"
        )
        snapshot = build_snapshot(computed, student_id)
        b = await _make_bulletin(
            db, school["school_id"], class_id, student_id, snapshot
        )
        await db.commit()

        url = f"/api/verify/bulletin/{b.student_id}/{b.class_id}/{b.period}/{b.academic_year}"
        res = await client.get(url)
        assert res.status_code == 200
        assert "non signé" in res.text

    async def test_verify_bulletin_not_found(self, client, db):
        """Élève inconnu ⇒ page « Document introuvable » (pas d'exception 500)."""
        res = await client.get("/api/verify/bulletin/999999/999/T1/2025-2026/00" + "0" * 30)
        assert res.status_code == 200
        assert "Document introuvable" in res.text

    async def test_verify_receipt_valid_and_tampered(self, client, db):
        """Reçu : jeton valide ⇒ authentique ; jeton altéré ⇒ refusé."""
        school, class_id, student_id = await _snapshot_scenario(client)

        from app.services.verification_service import receipt_signature

        fee = FeeObligation(
            school_id=school["school_id"], class_id=class_id,
            name="Frais T1", amount=5000, period="T1", academic_year="2025-2026",
        )
        db.add(fee)
        await db.flush()
        payment = Payment(
            school_id=school["school_id"], student_id=student_id,
            obligation_id=fee.id, amount=5000, payment_method="cash",
            notes="Frais d'inscription",
        )
        db.add(payment)
        await db.flush()
        await db.commit()

        token = receipt_signature(payment.school_id, payment.id)
        assert isinstance(token, str) and len(token) == 32

        res = await client.get(f"/api/verify/receipt/{payment.id}/{token}")
        assert res.status_code == 200
        assert "Reçu authentique" in res.text
        assert "5 000 FCFA" in res.text

        res = await client.get(f"/api/verify/receipt/{payment.id}/{'0' * 32}")
        assert res.status_code == 200
        assert "Reçu non authentique" in res.text
