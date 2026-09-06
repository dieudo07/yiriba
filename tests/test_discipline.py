"""Yiriba SaaS — Discipline module tests.

Tests:
1. Unit: grade_calculator functions
2. Unit: discipline service functions
3. Integration: auto-record from attendance
4. Integration: manual record creation
5. Integration: cancellation (soft delete)
6. Integration: total deductions
7. Integration: general_average mode
8. Integration: justification cancels auto-record
"""

import pytest
from datetime import date
from httpx import AsyncClient
from sqlalchemy import select

from app.models.discipline import DisciplinaryRecord, DisciplinaryRuleSet
from app.models.school import School
from app.services.grade_calculator import (
    calculate_overall_average, calculate_conduct_score,
    apply_discipline, get_mention,
)
from app.services.discipline_service import (
    create_record_from_attendance, cancel_record_on_justification,
    create_manual_record, cancel_record, get_total_deductions,
    seed_default_rules,
)
from app.models.attendance import StatutPresence


# ── Helpers ─────────────────────────────────────────────────────

async def _register_school(client: AsyncClient, slug: str = "disc-test") -> dict:
    import uuid
    uid = str(uuid.uuid4())[:8]
    s = f"{slug}-{uid}"
    res = await client.post("/api/auth/register-school", json={
        "school_name": f"Test {s}",
        "school_slug": s,
        "school_type": "college",
        "school_country": "Burkina Faso",
        "school_city": "Ouaga",
        "admin_first_name": "Admin",
        "admin_last_name": "Test",
        "admin_email": f"admin_{uid}@test.com",
        "admin_password": "Test1234!",
    })
    data = res.json()
    # Pas d'auto-login : login avec le mot de passe temporaire.
    login = await client.post("/api/auth/login", json={
        "email": f"admin_{uid}@test.com", "password": data["admin"]["temp_password"],
    })
    return {"token": login.json()["access_token"], "school_id": data["school"]["id"]}


def _auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


# ── Unit tests (no DB) ──────────────────────────────────────────


class TestGradeCalculator:
    """Test shared grade calculation functions."""

    def test_calculate_overall_average_basic(self):
        subjects = [
            {"average": 14.0, "coefficient": 4},
            {"average": 12.0, "coefficient": 3},
            {"average": 16.0, "coefficient": 2},
        ]
        # (14*4 + 12*3 + 16*2) / (4+3+2) = (56+36+32)/9 = 124/9 = 13.78
        assert calculate_overall_average(subjects) == 13.78

    def test_calculate_overall_average_with_none(self):
        subjects = [
            {"average": 14.0, "coefficient": 4},
            {"average": None, "coefficient": 3},
        ]
        assert calculate_overall_average(subjects) == 14.0

    def test_calculate_overall_average_empty(self):
        # Aucune note -> None (bulletin incomplet, pas de faux 0.00)
        assert calculate_overall_average([]) is None
        assert calculate_overall_average([{"average": None, "coefficient": 3}]) is None

    def test_conduct_score_full(self):
        assert calculate_conduct_score(0) == 20.0

    def test_conduct_score_with_deductions(self):
        assert calculate_conduct_score(1.5) == 18.5

    def test_conduct_score_floor_at_zero(self):
        assert calculate_conduct_score(25.0) == 0.0

    def test_apply_discipline_conduct_mode(self):
        result = apply_discipline(14.5, "conduct", 1.5)
        assert result["display_average"] == 14.5  # Unchanged
        assert result["conduct_score"] == 18.5     # 20 - 1.5
        assert result["discipline_deduction"] == 0.0

    def test_apply_discipline_general_average_mode(self):
        result = apply_discipline(14.5, "general_average", 1.5)
        assert result["display_average"] == 13.0   # 14.5 - 1.5
        assert result["conduct_score"] is None
        assert result["discipline_deduction"] == 1.5

    def test_apply_discipline_general_average_floor(self):
        result = apply_discipline(1.0, "general_average", 5.0)
        assert result["display_average"] == 0.0    # Floor at 0

    def test_apply_discipline_no_deductions(self):
        result = apply_discipline(14.5, "general_average", 0.0)
        assert result["display_average"] == 14.5   # No change when 0 deductions

    def test_get_mention(self):
        assert get_mention(16.0) == "Félicitations"
        assert get_mention(14.0) == "Encouragements"
        assert get_mention(12.0) == "Tableau d'honneur"
        assert get_mention(10.0) == "Passable"
        assert get_mention(8.0) == "Avertissement"


# ── Integration tests ───────────────────────────────────────────


@pytest.mark.integration
class TestDisciplineRules:
    """Test rule management."""

    async def test_seed_default_rules(self, client: AsyncClient, db):
        school = await _register_school(client, "rules-seed")
        await seed_default_rules(db, school["school_id"])
        await db.flush()

        rules = (await db.execute(
            select(DisciplinaryRuleSet).where(
                DisciplinaryRuleSet.school_id == school["school_id"]
            )
        )).scalars().all()

        assert len(rules) == 3
        types = {r.incident_type for r in rules}
        assert "absence_non_justifiee" in types
        assert "retard" in types
        assert "incivilite" in types

    async def test_upsert_rule_via_api(self, client: AsyncClient, db):
        school = await _register_school(client, "rules-api")
        h = _auth(school["token"])

        res = await client.put("/api/discipline/rules", json={
            "incident_type": "absence_non_justifiee",
            "points_deducted": 1.0,
            "description": "Absence grave",
        }, headers=h)
        assert res.status_code == 200
        assert res.json()["points_deducted"] == 1.0

        # Upsert same type — should update
        res = await client.put("/api/discipline/rules", json={
            "incident_type": "absence_non_justifiee",
            "points_deducted": 0.75,
        }, headers=h)
        assert res.status_code == 200
        assert res.json()["points_deducted"] == 0.75


@pytest.mark.integration
class TestAutoRecordFromAttendance:
    """Test automatic disciplinary record creation from attendance."""

    async def test_absence_creates_record(self, client: AsyncClient, db):
        school = await _register_school(client, "auto-abs")
        h = _auth(school["token"])

        # Seed rules
        await seed_default_rules(db, school["school_id"])
        await db.flush()

        # Create class + student
        res = await client.post("/api/classes", json={
            "name": "6e A", "period_type": "trimestre",
        }, headers=h)
        class_id = res.json()["id"]

        res = await client.post("/api/students", json={
            "first_name": "Test", "last_name": "Auto",
            "gender": "M",
        }, headers=h)
        student_id = res.json()["id"]

        # Mark absence
        res = await client.post("/api/attendance/bulk", json={
            "class_id": class_id,
            "date": "2025-10-01",
            "period": "T1",
            "slot_index": 0,
            "entries": [{"student_id": student_id, "status": "absent"}],
        }, headers=h)
        assert res.status_code == 201

        # Check disciplinary record was created
        records = (await db.execute(
            select(DisciplinaryRecord).where(
                DisciplinaryRecord.school_id == school["school_id"],
                DisciplinaryRecord.student_id == student_id,
            )
        )).scalars().all()

        assert len(records) == 1
        assert records[0].incident_type == "absence_non_justifiee"
        assert records[0].points_deducted == 0.5
        assert records[0].source == "auto"
        assert records[0].status == "active"

    async def test_justified_absence_no_record(self, client: AsyncClient, db):
        school = await _register_school(client, "auto-just")
        h = _auth(school["token"])

        await seed_default_rules(db, school["school_id"])
        await db.flush()

        res = await client.post("/api/classes", json={
            "name": "6e A", "period_type": "trimestre",
        }, headers=h)
        class_id = res.json()["id"]

        res = await client.post("/api/students", json={
            "first_name": "Test", "last_name": "Justifie",
            "gender": "M",
        }, headers=h)
        student_id = res.json()["id"]

        # Mark justified absence
        res = await client.post("/api/attendance/bulk", json={
            "class_id": class_id,
            "date": "2025-10-02",
            "period": "T1",
            "slot_index": 0,
            "entries": [{"student_id": student_id, "status": "absent", "is_justified": True}],
        }, headers=h)
        assert res.status_code == 201

        # No disciplinary record should exist
        records = (await db.execute(
            select(DisciplinaryRecord).where(
                DisciplinaryRecord.school_id == school["school_id"],
                DisciplinaryRecord.student_id == student_id,
            )
        )).scalars().all()
        assert len(records) == 0


@pytest.mark.integration
class TestManualRecord:
    """Test manual disciplinary record creation."""

    async def test_create_manual_record(self, client: AsyncClient, db):
        school = await _register_school(client, "manual-rec")
        h = _auth(school["token"])

        await seed_default_rules(db, school["school_id"])
        await db.flush()

        res = await client.post("/api/students", json={
            "first_name": "Test", "last_name": "Manuel",
            "gender": "M",
        }, headers=h)
        student_id = res.json()["id"]

        res = await client.post("/api/discipline/records", json={
            "student_id": student_id,
            "period": "T1",
            "academic_year": "2025-2026",
            "incident_type": "incivilite",
            "date": "2025-10-05",
            "note": "Perturbation en classe",
        }, headers=h)
        assert res.status_code == 201
        assert res.json()["incident_type"] == "incivilite"
        assert res.json()["points_deducted"] == 1.0


@pytest.mark.integration
class TestCancellation:
    """Test record cancellation (soft delete)."""

    async def test_cancel_record(self, client: AsyncClient, db):
        school = await _register_school(client, "cancel-rec")
        h = _auth(school["token"])

        await seed_default_rules(db, school["school_id"])
        await db.flush()

        res = await client.post("/api/students", json={
            "first_name": "Test", "last_name": "Annuler",
            "gender": "M",
        }, headers=h)
        student_id = res.json()["id"]

        # Create record
        res = await client.post("/api/discipline/records", json={
            "student_id": student_id,
            "period": "T1",
            "academic_year": "2025-2026",
            "incident_type": "retard",
            "date": "2025-10-05",
        }, headers=h)
        record_id = res.json()["id"]

        # Cancel it
        res = await client.put(f"/api/discipline/records/{record_id}/cancel", json={
            "reason": "Retard justifié",
        }, headers=h)
        assert res.status_code == 200
        assert res.json()["status"] == "cancelled"
        assert res.json()["cancel_reason"] == "Retard justifié"


@pytest.mark.integration
class TestTotalDeductions:
    """Test total deduction calculation."""

    async def test_get_total_deductions(self, client: AsyncClient, db):
        school = await _register_school(client, "total-ded")
        h = _auth(school["token"])

        await seed_default_rules(db, school["school_id"])
        await db.flush()

        res = await client.post("/api/students", json={
            "first_name": "Test", "last_name": "Deductions",
            "gender": "M",
        }, headers=h)
        student_id = res.json()["id"]

        # Create 2 records
        for itype in ["absence_non_justifiee", "retard"]:
            await client.post("/api/discipline/records", json={
                "student_id": student_id,
                "period": "T1",
                "academic_year": "2025-2026",
                "incident_type": itype,
                "date": "2025-10-05",
            }, headers=h)

        total = await get_total_deductions(
            db, school["school_id"], student_id, "T1", "2025-2026"
        )
        # 0.5 (absence) + 0.25 (retard) = 0.75
        assert total == 0.75

    async def test_cancelled_record_not_counted(self, client: AsyncClient, db):
        school = await _register_school(client, "cancel-ded")
        h = _auth(school["token"])

        await seed_default_rules(db, school["school_id"])
        await db.flush()

        res = await client.post("/api/students", json={
            "first_name": "Test", "last_name": "Cancel",
            "gender": "M",
        }, headers=h)
        student_id = res.json()["id"]

        # Create record
        res = await client.post("/api/discipline/records", json={
            "student_id": student_id,
            "period": "T1",
            "academic_year": "2025-2026",
            "incident_type": "absence_non_justifiee",
            "date": "2025-10-05",
        }, headers=h)
        record_id = res.json()["id"]

        # Total = 0.5
        total = await get_total_deductions(
            db, school["school_id"], student_id, "T1", "2025-2026"
        )
        assert total == 0.5

        # Cancel it
        await client.put(f"/api/discipline/records/{record_id}/cancel", json={
            "reason": "Test",
        }, headers=h)

        # Total = 0
        total = await get_total_deductions(
            db, school["school_id"], student_id, "T1", "2025-2026"
        )
        assert total == 0.0


@pytest.mark.integration
class TestDisciplineMode:
    """Test school discipline mode configuration."""

    async def test_default_mode_is_conduct(self, client: AsyncClient, db):
        school = await _register_school(client, "mode-def")
        h = _auth(school["token"])

        res = await client.get("/api/discipline/mode", headers=h)
        assert res.status_code == 200
        assert res.json()["mode"] == "conduct"

    async def test_switch_to_general_average(self, client: AsyncClient, db):
        school = await _register_school(client, "mode-gen")
        h = _auth(school["token"])

        res = await client.put("/api/discipline/mode", json={
            "mode": "general_average",
        }, headers=h)
        assert res.status_code == 200
        assert res.json()["mode"] == "general_average"

        # Verify it persists
        res = await client.get("/api/discipline/mode", headers=h)
        assert res.json()["mode"] == "general_average"
