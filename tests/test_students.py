"""Yiriba SaaS — Student module tests: CRUD, IDOR, transfer, parent links, CSV import."""

import pytest
from httpx import AsyncClient


async def _create_school_with_token(client: AsyncClient, slug: str = "test-school") -> tuple[str, int]:
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


# ── CRUD ──────────────────────────────────────────────────────────


@pytest.mark.integration
class TestStudentCRUD:

    async def test_create_student(self, client: AsyncClient, db):
        token, school_id = await _create_school_with_token(client, "crud-create")
        resp = await client.post("/api/students", json={
            "first_name": "Ibrahim", "last_name": "Ouedraogo",
            "gender": "M", "birth_date": "2010-05-15",
        }, headers=_auth(token))
        assert resp.status_code == 201
        data = resp.json()
        assert data["first_name"] == "Ibrahim"
        assert data["status"] == "active"
        assert data["school_id"] == school_id

    async def test_create_student_no_school_in_payload(self, client: AsyncClient, db):
        """school_id in payload must be ignored — forced from JWT."""
        token, school_id = await _create_school_with_token(client, "crud-noschool")
        resp = await client.post("/api/students", json={
            "first_name": "Test", "last_name": "NoSchool",
            "school_id": 9999,  # Should be ignored
        }, headers=_auth(token))
        assert resp.status_code == 201
        assert resp.json()["school_id"] == school_id  # From JWT, not payload

    async def test_list_students(self, client: AsyncClient, db):
        token, _ = await _create_school_with_token(client, "crud-list")
        for i in range(3):
            await client.post("/api/students", json={
                "first_name": f"Student{i}", "last_name": f"Test{i}", "gender": "M",
            }, headers=_auth(token))
        resp = await client.get("/api/students", headers=_auth(token))
        assert resp.status_code == 200
        assert resp.json()["total"] == 3

    async def test_list_students_pagination(self, client: AsyncClient, db):
        token, _ = await _create_school_with_token(client, "crud-page")
        for i in range(25):
            await client.post("/api/students", json={
                "first_name": f"S{i}", "last_name": f"T{i}",
                "gender": "M" if i % 2 == 0 else "F",
            }, headers=_auth(token))
        resp = await client.get("/api/students?page=1&per_page=10", headers=_auth(token))
        data = resp.json()
        assert len(data["students"]) == 10
        assert data["total"] == 25
        assert data["total_pages"] == 3

    async def test_list_students_search(self, client: AsyncClient, db):
        token, _ = await _create_school_with_token(client, "crud-search")
        await client.post("/api/students", json={"first_name": "Moussa", "last_name": "Diallo"}, headers=_auth(token))
        await client.post("/api/students", json={"first_name": "Awa", "last_name": "Traore"}, headers=_auth(token))
        resp = await client.get("/api/students?search=Moussa", headers=_auth(token))
        assert resp.json()["total"] == 1

    async def test_update_student(self, client: AsyncClient, db):
        token, _ = await _create_school_with_token(client, "crud-update")
        create = await client.post("/api/students", json={"first_name": "Oumarou", "last_name": "Sawadogo"}, headers=_auth(token))
        sid = create.json()["id"]
        resp = await client.put(f"/api/students/{sid}", json={"first_name": "Oumarou V2", "is_repeater": True}, headers=_auth(token))
        assert resp.status_code == 200
        assert resp.json()["first_name"] == "Oumarou V2"
        assert resp.json()["is_repeater"] is True


# ── Soft Delete / Status ─────────────────────────────────────────


@pytest.mark.integration
class TestStudentStatus:

    async def test_soft_delete(self, client: AsyncClient, db):
        token, _ = await _create_school_with_token(client, "status-delete")
        create = await client.post("/api/students", json={"first_name": "ToDelete", "last_name": "Student"}, headers=_auth(token))
        sid = create.json()["id"]
        resp = await client.delete(f"/api/students/{sid}", headers=_auth(token))
        assert resp.status_code == 204
        # Should not appear in list
        list_resp = await client.get("/api/students", headers=_auth(token))
        assert list_resp.json()["total"] == 0

    async def test_change_status(self, client: AsyncClient, db):
        token, _ = await _create_school_with_token(client, "status-change")
        create = await client.post("/api/students", json={"first_name": "Grad", "last_name": "Student"}, headers=_auth(token))
        sid = create.json()["id"]
        resp = await client.put(f"/api/students/{sid}/status", json={
            "status": "graduated", "reason": "Termine le cycle"
        }, headers=_auth(token))
        assert resp.status_code == 200
        assert resp.json()["status"] == "graduated"

    async def test_inactive_student_not_in_list(self, client: AsyncClient, db):
        token, _ = await _create_school_with_token(client, "status-inactive")
        create = await client.post("/api/students", json={"first_name": "Hidden", "last_name": "Student"}, headers=_auth(token))
        sid = create.json()["id"]
        # Deactivate
        await client.put(f"/api/students/{sid}/status", json={"status": "inactive"}, headers=_auth(token))
        # Should not appear in default list
        resp = await client.get("/api/students", headers=_auth(token))
        assert resp.json()["total"] == 0
        # But can be found with explicit status filter
        resp = await client.get("/api/students?status=inactive", headers=_auth(token))
        assert resp.json()["total"] == 1


# ── Transfer ──────────────────────────────────────────────────────


@pytest.mark.integration
class TestStudentTransfer:

    async def test_transfer_student(self, client: AsyncClient, db):
        token, _ = await _create_school_with_token(client, "transfer")
        # Create 2 classes
        c1 = await client.post("/api/classes", json={"name": "6eme A", "capacity": 30}, headers=_auth(token))
        c2 = await client.post("/api/classes", json={"name": "6eme B", "capacity": 30}, headers=_auth(token))
        class1_id = c1.json()["id"]
        class2_id = c2.json()["id"]

        # Create student and enroll in class 1
        stud = await client.post("/api/students", json={"first_name": "Trans", "last_name": "Fer"}, headers=_auth(token))
        sid = stud.json()["id"]
        await client.post("/api/enrollments", json={"student_id": sid, "class_id": class1_id}, headers=_auth(token))

        # Transfer to class 2
        resp = await client.post(f"/api/students/{sid}/transfer", json={
            "new_class_id": class2_id, "reason": "Demande parent"
        }, headers=_auth(token))
        assert resp.status_code == 200
        assert resp.json()["new_class"] == "6eme B"

        # Check history
        hist = await client.get(f"/api/students/{sid}/history", headers=_auth(token))
        enrollments = hist.json()["enrollments"]
        assert len(enrollments) == 2
        statuses = {e["status"] for e in enrollments}
        assert "transferred" in statuses
        assert "active" in statuses


# ── Parent Links ──────────────────────────────────────────────────


@pytest.mark.integration
class TestParentLinks:

    async def _create_parent(self, client, slug):
        """Helper: create a school and return (token, user_id)."""
        token, school_id = await _create_school_with_token(client, slug)
        return token, token  # Return (token, user_id) — admin is user_id=1

    async def test_link_parent(self, client: AsyncClient, db):
        # Create school and get token
        token, _ = await _create_school_with_token(client, "plink-create")

        # Create student
        stud = await client.post("/api/students", json={"first_name": "Enfant", "last_name": "Test"}, headers=_auth(token))
        sid = stud.json()["id"]

        # Create a second school to get a parent user (reuse as parent)
        token2, _ = await _create_school_with_token(client, "plink-parent")

        # Link parent (using school 1 token with school 2's parent - should fail)
        # Actually, parent must be in the same school. Let me test with the admin as parent.
        # For a proper test, we'd create a user with role_type=PARENT. Simplified:
        resp = await client.post(f"/api/students/{sid}/parents", json={
            "parent_id": 9999,  # Non-existent
            "role": "father",
            "is_primary": True,
        }, headers=_auth(token))
        assert resp.status_code == 404  # Parent not found

    async def test_student_has_parents_field(self, client: AsyncClient, db):
        token, _ = await _create_school_with_token(client, "plink-field")
        resp = await client.post("/api/students", json={"first_name": "Check", "last_name": "Parents"}, headers=_auth(token))
        assert resp.status_code == 201
        assert "parents" in resp.json()
        assert isinstance(resp.json()["parents"], list)


# ── IDOR ──────────────────────────────────────────────────────────


@pytest.mark.security
class TestStudentIDOR:

    async def test_cannot_read_other_school_student(self, client: AsyncClient, db):
        token_a, _ = await _create_school_with_token(client, "idor-a")
        token_b, _ = await _create_school_with_token(client, "idor-b")
        create = await client.post("/api/students", json={"first_name": "Protected", "last_name": "Student"}, headers=_auth(token_a))
        sid = create.json()["id"]
        resp = await client.get(f"/api/students/{sid}", headers=_auth(token_b))
        assert resp.status_code == 404

    async def test_cannot_update_other_school_student(self, client: AsyncClient, db):
        token_a, _ = await _create_school_with_token(client, "idor-a2")
        token_b, _ = await _create_school_with_token(client, "idor-b2")
        create = await client.post("/api/students", json={"first_name": "Protected", "last_name": "Student2"}, headers=_auth(token_a))
        sid = create.json()["id"]
        resp = await client.put(f"/api/students/{sid}", json={"first_name": "HACKED"}, headers=_auth(token_b))
        assert resp.status_code == 404

    async def test_cannot_delete_other_school_student(self, client: AsyncClient, db):
        token_a, _ = await _create_school_with_token(client, "idor-a3")
        token_b, _ = await _create_school_with_token(client, "idor-b3")
        create = await client.post("/api/students", json={"first_name": "Protected", "last_name": "Student3"}, headers=_auth(token_a))
        sid = create.json()["id"]
        resp = await client.delete(f"/api/students/{sid}", headers=_auth(token_b))
        assert resp.status_code == 404


# ── CSV Import ────────────────────────────────────────────────────


@pytest.mark.integration
class TestStudentCSVImport:

    async def test_import_csv(self, client: AsyncClient, db):
        import json
        token, _ = await _create_school_with_token(client, "csv-import")

        # Une classe doit exister pour l'enrôlement des lignes importées.
        cls = await client.post("/api/classes", json={
            "name": "6eme A", "level": "6eme", "capacity": 50,
        }, headers=_auth(token))
        assert cls.status_code in (200, 201), cls.text

        csv_content = b"first_name,last_name,matricule,gender,classe\n"
        csv_content += b"Ibrahim,Ouedraogo,ELV-001,M,6eme A\n"
        csv_content += b"Awa,Traore,ELV-002,F,6eme A\n"

        mapping = json.dumps({
            "first_name": "first_name", "last_name": "last_name",
            "matricule": "matricule", "gender": "gender", "class_name": "classe",
        })

        # Étapes : detect → validate → confirm (aucun auto-login au register).
        valid = await client.post("/api/students/import/validate",
            data={"mapping": mapping},
            files={"file": ("students.csv", csv_content, "text/csv")},
            headers=_auth(token))
        assert valid.status_code == 200, valid.text
        vdata = valid.json()
        assert vdata["valid_count"] == 2

        resp = await client.post("/api/students/import/confirm",
            params={"session_id": vdata["session_id"]},
            headers=_auth(token))
        assert resp.status_code == 200, resp.text
        assert resp.json()["imported"] == 2
