"""Yiriba SaaS -- period_type immutability tests.

Verifies:
1. period_type CAN be changed on a class with no evaluations
2. period_type CANNOT be changed on a class that has evaluations
3. Error message is explicit when change is rejected
"""

import pytest
from httpx import AsyncClient


async def _create_school_with_token(client: AsyncClient, slug: str = "period-test") -> tuple[str, int]:
    response = await client.post("/api/auth/register-school", json={
        "school_name": f"Test {slug}",
        "school_slug": slug,
        "admin_email": f"admin@{slug}.com",
        "admin_password": "SecurePass123",
        "admin_first_name": "Admin",
        "admin_last_name": "Test",
    })
    data = response.json()
    # Pas d'auto-login au register : login avec le mot de passe temporaire.
    login = await client.post("/api/auth/login", json={
        "email": f"admin@{slug}.com", "password": data["admin"]["temp_password"],
    })
    assert login.status_code == 200, f"Login failed: {login.text}"
    return login.json()["access_token"], data["school"]["id"]


def _auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


@pytest.mark.integration
class TestPeriodTypeImmutability:

    async def test_change_period_type_before_evaluations(self, client: AsyncClient, db):
        """period_type CAN be changed when class has no evaluations."""
        token, school_id = await _create_school_with_token(client, "period-before")

        # Create class with trimestre
        resp = await client.post("/api/classes", json={
            "name": "6e A",
            "period_type": "trimestre",
        }, headers=_auth(token))
        assert resp.status_code == 201
        data = resp.json()
        class_id = data["id"]
        assert data["period_type"] == "trimestre"

        # Change to semestre -- should succeed
        resp = await client.put(f"/api/classes/{class_id}", json={
            "period_type": "semestre",
        }, headers=_auth(token))
        assert resp.status_code == 200
        assert resp.json()["period_type"] == "semestre"

    async def test_change_period_type_after_evaluations_rejected(self, client: AsyncClient, db):
        """period_type CANNOT be changed when class has evaluations."""
        token, school_id = await _create_school_with_token(client, "period-after")

        # Create class with trimestre
        resp = await client.post("/api/classes", json={
            "name": "5e B",
            "period_type": "trimestre",
        }, headers=_auth(token))
        assert resp.status_code == 201
        class_id = resp.json()["id"]

        # Create a subject
        resp = await client.post("/api/subjects", json={
            "name": "Mathematiques",
        }, headers=_auth(token))
        assert resp.status_code == 201
        subject_id = resp.json()["id"]

        # Link subject to class via /api/class-subjects
        resp = await client.post("/api/class-subjects", json={
            "class_id": class_id,
            "subject_id": subject_id,
            "coefficient": 3,
        }, headers=_auth(token))
        assert resp.status_code in (200, 201), f"Could not link subject: {resp.status_code} {resp.text}"

        # Create an evaluation (requires 'name' and 'date' fields)
        resp = await client.post("/api/grades/evaluations", json={
            "class_id": class_id,
            "subject_id": subject_id,
            "name": "Devoir 1",
            "assessment_type": "devoir",
            "period": "T1",
            "max_grade": 20,
            "coefficient": 1,
            "date": "2025-10-01",
        }, headers=_auth(token))
        assert resp.status_code in (200, 201), f"Failed to create evaluation: {resp.status_code} {resp.text}"

        # Try to change period_type -- should fail with 400
        resp = await client.put(f"/api/classes/{class_id}", json={
            "period_type": "semestre",
        }, headers=_auth(token))
        assert resp.status_code == 400
        detail = resp.json()["detail"]
        assert "period" in detail.lower() or "periode" in detail.lower() or "evaluation" in detail.lower(), \
            f"Error message should mention period/evaluation, got: {detail}"

    async def test_change_period_type_error_message_is_explicit(self, client: AsyncClient, db):
        """The rejection error message must be clear and actionable."""
        token, school_id = await _create_school_with_token(client, "period-msg")

        # Create class
        resp = await client.post("/api/classes", json={
            "name": "4e A",
            "period_type": "trimestre",
        }, headers=_auth(token))
        class_id = resp.json()["id"]

        # Create subject + link + evaluation
        resp = await client.post("/api/subjects", json={"name": "Francais"}, headers=_auth(token))
        subject_id = resp.json()["id"]

        resp = await client.post("/api/class-subjects", json={
            "class_id": class_id,
            "subject_id": subject_id,
            "coefficient": 2,
        }, headers=_auth(token))
        assert resp.status_code in (200, 201)

        resp = await client.post("/api/grades/evaluations", json={
            "class_id": class_id,
            "subject_id": subject_id,
            "name": "Devoir 1",
            "assessment_type": "devoir",
            "period": "T1",
            "max_grade": 20,
            "coefficient": 1,
            "date": "2025-10-01",
        }, headers=_auth(token))
        assert resp.status_code in (200, 201)

        # Attempt change -- verify error message is explicit
        resp = await client.put(f"/api/classes/{class_id}", json={
            "period_type": "semestre",
        }, headers=_auth(token))
        assert resp.status_code == 400
        detail = resp.json()["detail"]
        assert "evaluation" in detail.lower() or "definitif" in detail.lower(), \
            f"Error message too vague: {detail}"
        print(f"   -> Error message: {detail}")

    async def test_same_period_type_accepted_even_with_evaluations(self, client: AsyncClient, db):
        """Setting the SAME period_type should succeed (no-op)."""
        token, school_id = await _create_school_with_token(client, "period-same")

        # Create class
        resp = await client.post("/api/classes", json={
            "name": "3e C",
            "period_type": "trimestre",
        }, headers=_auth(token))
        class_id = resp.json()["id"]

        # Create subject + link + evaluation
        resp = await client.post("/api/subjects", json={"name": "SVT"}, headers=_auth(token))
        subject_id = resp.json()["id"]

        resp = await client.post("/api/class-subjects", json={
            "class_id": class_id,
            "subject_id": subject_id,
            "coefficient": 2,
        }, headers=_auth(token))
        assert resp.status_code in (200, 201)

        resp = await client.post("/api/grades/evaluations", json={
            "class_id": class_id,
            "subject_id": subject_id,
            "name": "Devoir 1",
            "assessment_type": "devoir",
            "period": "T1",
            "max_grade": 20,
            "coefficient": 1,
            "date": "2025-10-01",
        }, headers=_auth(token))
        assert resp.status_code in (200, 201)

        # Set same period_type -- should succeed
        resp = await client.put(f"/api/classes/{class_id}", json={
            "period_type": "trimestre",
        }, headers=_auth(token))
        assert resp.status_code == 200
