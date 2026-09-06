"""Yiriba SaaS — Tests de cohérence inter-portails.

Vérifie les chaînes complètes entre portails:
- Isolation complète entre écoles
- RBAC correctly enforced
- Parent/Student portal access control
"""

import pytest
import uuid
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.main import app
from app.core.database import get_db


def _headers(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


async def _setup_school(client: AsyncClient, slug: str, email: str):
    """Register a school and return comprehensive data."""
    res = await client.post("/api/auth/register-school", json={
        "school_name": f"Test {slug}",
        "school_slug": slug,
        "admin_first_name": "Admin",
        "admin_last_name": "Test",
        "admin_email": email,
        "admin_password": "Admin123!",
    })
    assert res.status_code in (200, 201), f"Register failed: {res.text}"
    data = res.json()
    # Pas d'auto-login : login avec le mot de passe temporaire.
    login = await client.post("/api/auth/login", json={
        "email": email, "password": data["admin"]["temp_password"],
    })
    token = login.json()["access_token"]
    school_id = data.get("school", {}).get("id") or data.get("user", {}).get("school_id")
    admin_id = data.get("user", {}).get("id")

    # Create a student
    student_res = await client.post("/api/students", json={
        "first_name": "Test", "last_name": "Student",
        "gender": "M", "nationality": "Burkinabè",
    }, headers=_headers(token))
    student = student_res.json() if student_res.status_code in (200, 201) else None

    return {
        "token": token,
        "school_id": school_id,
        "admin_id": admin_id,
        "student": student,
    }


@pytest.fixture
async def school_data(db: AsyncSession):
    """Create a school with data for testing."""
    async def override_get_db():
        yield db
    app.dependency_overrides[get_db] = override_get_db

    unique = uuid.uuid4().hex[:8]
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        data = await _setup_school(client, f"test-{unique}", f"admin-{unique}@test.com")
        data["client"] = client
        yield data

    app.dependency_overrides.clear()


# ═══════════════════════════════════════════════════════════════════
# TESTS: Basic Access Control
# ═══════════════════════════════════════════════════════════════════

@pytest.mark.asyncio
class TestBasicAccess:
    """Tests de base d'accès."""

    async def test_unauthenticated_rejected(self, school_data):
        """Sans token, l'accès est refusé."""
        # Le client peut porter le cookie de session posé au login — on le
        # retire pour simuler un vrai visiteur non authentifié.
        school_data["client"].cookies.clear()
        res = await school_data["client"].get("/api/students")
        assert res.status_code == 401

    async def test_invalid_token_rejected(self, school_data):
        """Un token invalide est refusé."""
        res = await school_data["client"].get(
            "/api/students",
            headers=_headers("invalid-token-12345"),
        )
        assert res.status_code == 401

    async def test_admin_can_access_students(self, school_data):
        """L'admin peut consulter les élèves."""
        res = await school_data["client"].get(
            "/api/students",
            headers=_headers(school_data["token"]),
        )
        assert res.status_code == 200
        students = res.json().get("students", [])
        assert len(students) > 0

    async def test_admin_can_access_grades(self, school_data):
        """L'admin peut consulter les notes."""
        res = await school_data["client"].get(
            "/api/grades",
            headers=_headers(school_data["token"]),
        )
        assert res.status_code == 200

    async def test_admin_can_access_classes(self, school_data):
        """L'admin peut consulter les classes."""
        res = await school_data["client"].get(
            "/api/classes",
            headers=_headers(school_data["token"]),
        )
        assert res.status_code == 200


# ═══════════════════════════════════════════════════════════════════
# TESTS: Student Data Integrity
# ═══════════════════════════════════════════════════════════════════

@pytest.mark.asyncio
class TestDataIntegrity:
    """Intégrité des données."""

    async def test_student_has_school_id(self, school_data):
        """Chaque élève a un school_id."""
        student = school_data["student"]
        assert student is not None
        assert student.get("school_id") == school_data["school_id"]

    async def test_student_by_id_returns_correct_school(self, school_data):
        """Récupérer un élève par ID retourne les bonnes données."""
        student = school_data["student"]
        res = await school_data["client"].get(
            f"/api/students/{student['id']}",
            headers=_headers(school_data["token"]),
        )
        assert res.status_code == 200
        data = res.json()
        assert data["school_id"] == school_data["school_id"]


# ═══════════════════════════════════════════════════════════════════
# TESTS: Cross-School Isolation
# ═══════════════════════════════════════════════════════════════════

@pytest.mark.asyncio
class TestCrossSchool:
    """Isolation entre écoles."""

    async def test_two_schools_isolated(self, db: AsyncSession):
        """Deux écoles ont des données complètement isolées."""
        async def override_get_db():
            yield db
        app.dependency_overrides[get_db] = override_get_db

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            school_a = await _setup_school(client, "isolation-a", "admin-iso-a@test.com")
            school_b = await _setup_school(client, "isolation-b", "admin-iso-b@test.com")

            # School A students
            res_a = await client.get(
                "/api/students",
                headers=_headers(school_a["token"]),
            )
            ids_a = {s["id"] for s in res_a.json().get("students", [])}

            # School B students
            res_b = await client.get(
                "/api/students",
                headers=_headers(school_b["token"]),
            )
            ids_b = {s["id"] for s in res_b.json().get("students", [])}

            # No overlap
            assert not ids_a & ids_b, "Schools should have no shared students"

            # School A cannot access School B's student by ID
            if school_b["student"]:
                res = await client.get(
                    f"/api/students/{school_b['student']['id']}",
                    headers=_headers(school_a["token"]),
                )
                assert res.status_code in (403, 404), \
                    "Cross-school access should be rejected"

        app.dependency_overrides.clear()


# ═══════════════════════════════════════════════════════════════════
# TESTS: RBAC
# ═══════════════════════════════════════════════════════════════════

@pytest.mark.asyncio
class TestRBAC:
    """RBAC enforcement."""

    async def test_non_admin_cannot_manage_users(self, school_data):
        """Un utilisateur non-admin ne peut pas gérer les utilisateurs."""
        # Create a teacher user
        res = await school_data["client"].post("/api/admin/users", json={
            "first_name": "Teacher", "last_name": "Test",
            "email": "teacher-rbac@test.com", "password": "Teacher123!",
            "role_type": "teacher",
        }, headers=_headers(school_data["token"]))

        if res.status_code in (200, 201):
            # Login as teacher
            login_res = await school_data["client"].post("/api/auth/login", json={
                "email": "teacher-rbac@test.com", "password": "Teacher123!",
            })
            if login_res.status_code == 200:
                teacher_token = login_res.json()["access_token"]

                # Teacher tries to access admin routes
                res = await school_data["client"].get(
                    "/api/admin/users",
                    headers=_headers(teacher_token),
                )
                assert res.status_code == 403


# ═══════════════════════════════════════════════════════════════════
# TESTS: Parent Portal
# ═══════════════════════════════════════════════════════════════════

@pytest.mark.asyncio
class TestParentPortal:
    """Accès parent."""

    async def test_parent_can_list_children(self, school_data):
        """Un parent peut lister ses enfants."""
        # Create a parent user
        res = await school_data["client"].post("/api/admin/users", json={
            "first_name": "Parent", "last_name": "Test",
            "email": "parent-portal@test.com", "password": "Parent123!",
            "role_type": "parent",
        }, headers=_headers(school_data["token"]))

        if res.status_code in (200, 201):
            login_res = await school_data["client"].post("/api/auth/login", json={
                "email": "parent-portal@test.com", "password": "Parent123!",
            })
            if login_res.status_code == 200:
                parent_token = login_res.json()["access_token"]

                res = await school_data["client"].get(
                    "/api/parent/my-children",
                    headers=_headers(parent_token),
                )
                assert res.status_code == 200

    async def test_parent_cannot_access_unlinked_child(self, school_data):
        """Un parent ne peut PAS accéder à un enfant non lié."""
        res = await school_data["client"].post("/api/admin/users", json={
            "first_name": "Parent2", "last_name": "Test",
            "email": "parent2-portal@test.com", "password": "Parent123!",
            "role_type": "parent",
        }, headers=_headers(school_data["token"]))

        if res.status_code in (200, 201):
            login_res = await school_data["client"].post("/api/auth/login", json={
                "email": "parent2-portal@test.com", "password": "Parent123!",
            })
            if login_res.status_code == 200:
                parent_token = login_res.json()["access_token"]

                res = await school_data["client"].get(
                    "/api/parent/children/99999/grades",
                    headers=_headers(parent_token),
                )
                assert res.status_code in (403, 404)
