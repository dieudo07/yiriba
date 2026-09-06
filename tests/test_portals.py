"""Yiriba SaaS — Portal IDOR tests.

Tests that verify cross-portal security:
- Teacher cannot access grades of a class they don't teach
- Parent cannot access data of a child they're not linked to
- Student cannot create grades (403)
- Comptable cannot create grades (403)
"""

import pytest
from httpx import AsyncClient

from app.core.security import hash_password


# --- Helpers ---


async def _register_school(client: AsyncClient, slug: str = "test-school"):
    """Register a school and return token + school_id + user_id."""
    res = await client.post("/api/auth/register-school", json={
        "school_name": f"School {slug}",
        "school_slug": slug,
        "admin_email": f"admin@{slug}.com",
        "admin_password": "SecurePass123",
        "admin_first_name": "Admin",
        "admin_last_name": "Test",
    })
    assert res.status_code in (200, 201)
    data = res.json()
    # Pas d'auto-login au register : le serveur renvoie un mot de passe temporaire.
    token = await _login(client, f"admin@{slug}.com", data["admin"]["temp_password"])
    return token, data["school"]["id"], data.get("user", {}).get("id")


async def _login(client: AsyncClient, email: str, password: str):
    """Login and return token."""
    res = await client.post("/api/auth/login", json={
        "email": email,
        "password": password,
    })
    assert res.status_code == 200
    return res.json()["access_token"]


async def _create_and_activate_user(client: AsyncClient, admin_token: str, email: str, role_type: str = "admin"):
    """Create a user via admin API, validate if needed, and return their token."""
    res = await client.post("/api/admin/users", json={
        "email": email,
        "first_name": "Test",
        "last_name": "User",
        "password": "SecurePass123",
        "role_type": role_type,
    }, headers={"Authorization": f"Bearer {admin_token}"})
    assert res.status_code in (200, 201), f"Create user failed: {res.text}"
    user_data = res.json()
    user_id = user_data["id"]
    status = user_data.get("status", "pending")

    # Only validate if the user is pending (admin sub-roles start pending)
    if status == "pending":
        res = await client.put(
            f"/api/admin/users/{user_id}/validate",
            headers={"Authorization": f"Bearer {admin_token}"}
        )
        assert res.status_code == 200

    return await _login(client, email, "SecurePass123")


# --- Tests ---


@pytest.mark.asyncio
class TestTeacherIDOR:
    """Teacher cannot access data from classes they don't teach."""

    async def test_teacher_cannot_access_other_class_students(self, client: AsyncClient):
        # Register school
        token, school_id, admin_id = await _register_school(client, "idor-teacher")

        # Create two classes
        res_a = await client.post("/api/classes", json={
            "name": "6ème A", "level": "6ème", "capacity": 30,
        }, headers={"Authorization": f"Bearer {token}"})
        class_a_id = res_a.json()["id"]

        res_b = await client.post("/api/classes", json={
            "name": "6ème B", "level": "6ème", "capacity": 30,
        }, headers={"Authorization": f"Bearer {token}"})
        class_b_id = res_b.json()["id"]

        # Create subject
        res_s = await client.post("/api/subjects", json={
            "name": "Maths", "coefficient": 4,
        }, headers={"Authorization": f"Bearer {token}"})
        subject_id = res_s.json()["id"]

        # Create a teacher via admin API
        teacher_token = await _create_and_activate_user(client, token, "teacher-idor@t.com", "teacher")

        # Teacher has no TeacherClass assignment → my-classes returns empty
        res = await client.get(
            "/api/teacher/my-classes",
            headers={"Authorization": f"Bearer {teacher_token}"}
        )
        assert res.status_code == 200
        assert len(res.json()["classes"]) == 0

        # Teacher tries to access class B students directly → 403
        res = await client.get(
            f"/api/teacher/my-students/{class_b_id}",
            headers={"Authorization": f"Bearer {teacher_token}"}
        )
        assert res.status_code == 403

        # Teacher tries to create grades for class B → 403
        # First create an evaluation as admin
        res = await client.post("/api/grades/evaluations", json={
            "class_id": class_b_id,
            "subject_id": subject_id,
            "name": "Devoir 1",
            "assessment_type": "devoir1",
            "period": "T1",
            "date": "2025-10-01",
        }, headers={"Authorization": f"Bearer {token}"})
        eval_id = res.json()["id"]

        res = await client.post("/api/teacher/grades/bulk", json={
            "evaluation_id": eval_id,
            "grades": [],
        }, headers={"Authorization": f"Bearer {teacher_token}"})
        assert res.status_code == 403


@pytest.mark.asyncio
class TestParentIDOR:
    """Parent cannot access data of children they're not linked to."""

    async def test_parent_cannot_access_unlinked_child(self, client: AsyncClient):
        # Register school
        token, school_id, admin_id = await _register_school(client, "idor-parent")

        # Create two students
        res1 = await client.post("/api/students", json={
            "first_name": "Yacouba",
            "last_name": "Belem",
            "gender": "M",
        }, headers={"Authorization": f"Bearer {token}"})
        student_a_id = res1.json()["id"]

        res2 = await client.post("/api/students", json={
            "first_name": "Awa",
            "last_name": "Traore",
            "gender": "F",
        }, headers={"Authorization": f"Bearer {token}"})
        student_b_id = res2.json()["id"]

        # Create a parent linked to student A only (via student link endpoint)
        parent_token = await _create_and_activate_user(client, token, "parent-idor@p.com", "parent")

        # Get parent user id from token
        from app.core.security import decode_token
        payload = decode_token(parent_token)
        parent_id = int(payload["sub"])

        # Link parent to student A only
        res = await client.post(
            f"/api/students/{student_a_id}/parents",
            json={"parent_id": parent_id, "role": "father", "is_primary": True},
            headers={"Authorization": f"Bearer {token}"}
        )
        assert res.status_code == 201

        # Parent CAN see student A's grades (empty but 200)
        res = await client.get(
            f"/api/parent/children/{student_a_id}/grades",
            headers={"Authorization": f"Bearer {parent_token}"}
        )
        assert res.status_code == 200

        # Parent CANNOT see student B's data (403)
        res = await client.get(
            f"/api/parent/children/{student_b_id}/grades",
            headers={"Authorization": f"Bearer {parent_token}"}
        )
        assert res.status_code == 403

        # Parent CANNOT see student B's attendance (403)
        res = await client.get(
            f"/api/parent/children/{student_b_id}/attendance",
            headers={"Authorization": f"Bearer {parent_token}"}
        )
        assert res.status_code == 403

        # Parent CAN see their linked child list
        res = await client.get(
            "/api/parent/my-children",
            headers={"Authorization": f"Bearer {parent_token}"}
        )
        assert res.status_code == 200
        children = res.json()["children"]
        assert len(children) == 1
        assert children[0]["id"] == student_a_id


@pytest.mark.asyncio
class TestStudentIDOR:
    """Student cannot modify grades — read-only portal."""

    async def test_student_cannot_create_grades(self, client: AsyncClient):
        # Register school
        token, school_id, admin_id = await _register_school(client, "idor-student2")

        # Create student
        res = await client.post("/api/students", json={
            "first_name": "Ibrahim",
            "last_name": "Tassembedo",
            "gender": "M",
        }, headers={"Authorization": f"Bearer {token}"})
        student_id = res.json()["id"]

        # Create student user account
        student_token = await _create_and_activate_user(client, token, "eleve-idor@s.com", "student")

        # Student CANNOT create evaluations (no evaluation.create permission)
        res = await client.post("/api/grades/evaluations", json={
            "class_id": 1,
            "subject_id": 1,
            "name": "Test",
            "assessment_type": "devoir1",
            "period": "T1",
            "date": "2025-10-01",
        }, headers={"Authorization": f"Bearer {student_token}"})
        assert res.status_code == 403

        # Student CANNOT create grades (no grade.create permission)
        res = await client.post("/api/grades", json={
            "evaluation_id": 1,
            "grades": [{"student_id": student_id, "grade": 20}],
        }, headers={"Authorization": f"Bearer {student_token}"})
        assert res.status_code == 403

        # Student CAN read their own grades (grade.read permission)
        res = await client.get(
            "/api/grades",
            headers={"Authorization": f"Bearer {student_token}"}
        )
        assert res.status_code == 200


@pytest.mark.asyncio
class TestComptableIDOR:
    """Comptable cannot create grades or manage users."""

    async def test_comptable_cannot_create_grades(self, client: AsyncClient):
        # Register school
        token, school_id, admin_id = await _register_school(client, "idor-comptable3")

        # Get the Comptable role ID
        res_roles = await client.get(
            "/api/admin/roles",
            headers={"Authorization": f"Bearer {token}"}
        )
        comptable_role_id = None
        for r in res_roles.json()["roles"]:
            if r["name"] == "Comptable":
                comptable_role_id = r["id"]
                break

        # Create comptable as admin type first
        res = await client.post("/api/admin/users", json={
            "email": "comptable-idor@c.com",
            "first_name": "Test",
            "last_name": "User",
            "password": "SecurePass123",
            "role_type": "admin",
            "role_id": comptable_role_id,
        }, headers={"Authorization": f"Bearer {token}"})
        assert res.status_code in (200, 201)
        user_data = res.json()
        user_id = user_data["id"]
        status = user_data.get("status", "pending")
        if status == "pending":
            await client.put(
                f"/api/admin/users/{user_id}/validate",
                headers={"Authorization": f"Bearer {token}"}
            )
        comptable_token = await _login(client, "comptable-idor@c.com", "SecurePass123")

        # Comptable CANNOT create evaluations (no evaluation.create permission)
        res = await client.post("/api/grades/evaluations", json={
            "class_id": 1,
            "subject_id": 1,
            "name": "Test",
            "assessment_type": "devoir1",
            "period": "T1",
            "date": "2025-10-01",
        }, headers={"Authorization": f"Bearer {comptable_token}"})
        assert res.status_code == 403

        # Comptable CAN read payments (has payment.read permission)
        res = await client.get(
            "/api/payments",
            headers={"Authorization": f"Bearer {comptable_token}"}
        )
        assert res.status_code == 200

        # Comptable CAN read students (has student.read permission)
        res = await client.get(
            "/api/students",
            headers={"Authorization": f"Bearer {comptable_token}"}
        )
        assert res.status_code == 200
