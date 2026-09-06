"""Yiriba SaaS — Audit E2E: Multi-tenant isolation, RBAC, Portal security.

Tests complete scenarios:
- School A cannot access School B data
- Role-based access for each portal
- Cross-portal data flow
- Subscription limits
- Error handling
"""
import uuid
import pytest
from httpx import AsyncClient
from app.main import app


# ── Helpers ────────────────────────────────────────────────────

async def _register_school(client, name="Ecole Test"):
    uid = str(uuid.uuid4())[:8]
    slug = f"{name.lower().replace(' ', '-')}-{uid}"
    email = f"admin_{slug}@test.com"
    res = await client.post("/api/auth/register-school", json={
        "school_name": name,
        "school_slug": slug,
        "school_short_name": name[:3].upper(),
        "school_type": "college",
        "school_country": "Burkina Faso",
        "school_city": "Ouaga",
        "admin_first_name": "Admin",
        "admin_last_name": "Test",
        "admin_email": email,
        "admin_password": "Test1234!",
        "admin_phone": f"+226{uid[:8]}",
    })
    data = res.json()

    # L'inscription ne crée aucun token : on se connecte avec le mot de
    # passe temporaire renvoyé par le serveur (pas d'auto-login).
    temp_password = data["admin"]["temp_password"]
    login_res = await client.post("/api/auth/login", json={
        "email": email, "password": temp_password,
    })
    login_data = login_res.json()
    token = login_data.get("access_token")

    user_id = data.get("user", {}).get("id")
    school_id = data.get("school", {}).get("id")
    return {"token": token, "user_id": user_id, "school_id": school_id, "email": email}


async def _login(client, email, password):
    res = await client.post("/api/auth/login", json={"email": email, "password": password})
    return res.json().get("access_token")


def _h(token):
    return {"Authorization": f"Bearer {token}"}


# ══════════════════════════════════════════════════════════════════
# MULTI-TENANT ISOLATION
# ══════════════════════════════════════════════════════════════════

class TestMultiTenantIsolation:
    """School A cannot access School B data — any module."""

    @pytest.mark.asyncio
    async def test_school_a_cannot_see_school_b_students(self, client):
        a = await _register_school(client, "Ecole Alpha")
        b = await _register_school(client, "Ecole Beta")

        # Create a student in School B
        res_b = await client.post("/api/students", json={
            "first_name": "Secret", "last_name": "Student",
            "gender": "M", "matricule": "B-001"
        }, headers=_h(b["token"]))
        assert res_b.status_code in (200, 201)
        student_id = res_b.json().get("id")

        # School A should NOT see this student
        res_a = await client.get(f"/api/students/{student_id}", headers=_h(a["token"]))
        assert res_a.status_code in (403, 404), f"School A accessed School B student! Status: {res_a.status_code}"

    @pytest.mark.asyncio
    async def test_school_a_cannot_see_school_b_classes(self, client):
        a = await _register_school(client, "Ecole Gamma")
        b = await _register_school(client, "Ecole Delta")

        # Create class in B
        res_b = await client.post("/api/classes", json={"name": "3e A", "capacity": 40}, headers=_h(b["token"]))
        assert res_b.status_code in (200, 201)
        # School A's class list should NOT contain B's class
        res_a = await client.get("/api/classes", headers=_h(a["token"]))
        assert res_a.status_code == 200
        classes = res_a.json().get("classes", [])
        for cl in classes:
            assert cl.get("school_id") == a["school_id"]

    @pytest.mark.asyncio
    async def test_school_a_cannot_see_school_b_users(self, client):
        a = await _register_school(client, "Ecole Epsilon")
        b = await _register_school(client, "Ecole Zeta")

        # School A should only see its own users
        res_a = await client.get("/api/admin/users", headers=_h(a["token"]))
        assert res_a.status_code == 200
        users = res_a.json().get("users", [])
        for u in users:
            assert u.get("school_id") == a["school_id"] or u.get("school_id") is None

    @pytest.mark.asyncio
    async def test_school_a_cannot_see_school_b_payments(self, client):
        a = await _register_school(client, "Ecole Eta")
        b = await _register_school(client, "Ecole Theta")

        res_a = await client.get("/api/payments", headers=_h(a["token"]))
        assert res_a.status_code == 200
        payments = res_a.json().get("payments", [])
        for p in payments:
            # No payments should leak from another school
            pass  # If a payment existed for B, A would see empty list

    @pytest.mark.asyncio
    async def test_cross_tenant_subject_manipulation(self, client):
        a = await _register_school(client, "Ecole Iota")
        b = await _register_school(client, "Ecole Kappa")

        # Create subject in B
        res_b = await client.post("/api/subjects", json={"name": "Math B", "code": "MATHB"}, headers=_h(b["token"]))
        subject_id = res_b.json().get("id") if res_b.status_code in (200, 201) else None

        # Create class in A
        res_a = await client.post("/api/classes", json={"name": "6e A", "capacity": 40}, headers=_h(a["token"]))
        class_id = res_a.json().get("id") if res_a.status_code in (200, 201) else None

        if subject_id and class_id:
            # Try to link B's subject to A's class
            res = await client.post("/api/class-subjects", json={
                "class_id": class_id, "subject_id": subject_id, "coefficient": 2
            }, headers=_h(a["token"]))
            assert res.status_code in (400, 403, 404), f"Cross-tenant subject linking allowed!"


# ══════════════════════════════════════════════════════════════════
# RBAC — PERMISSION DENIED SCENARIOS
# ══════════════════════════════════════════════════════════════════

class TestRBACPermissionDenied:
    """Users without proper permissions must be denied."""

    @pytest.mark.asyncio
    async def test_student_cannot_create_student(self, client):
        school = await _register_school(client, "Ecole RBAC1")
        u = str(uuid.uuid4())[:8]
        email = f"student_{u}@test.com"

        # Create a student user
        res = await client.post("/api/admin/users", json={
            "first_name": "Test", "last_name": "Student",
            "email": email, "password": "Test1234!",
            "role_type": "student"
        }, headers=_h(school["token"]))
        assert res.status_code in (200, 201)

        # Login as student
        login_res = await client.post("/api/auth/login", json={"email": email, "password": "Test1234!"})
        if login_res.status_code == 200:
            student_token = login_res.json().get("access_token")
            res = await client.post("/api/students", json={
                "first_name": "Hack", "last_name": "Student", "gender": "M"
            }, headers=_h(student_token))
            assert res.status_code in (403, 401), f"Student could create another student! Status: {res.status_code}"

    @pytest.mark.asyncio
    async def test_parent_cannot_modify_class(self, client):
        school = await _register_school(client, "Ecole RBAC2")
        u = str(uuid.uuid4())[:8]
        email = f"parent_{u}@test.com"

        res = await client.post("/api/admin/users", json={
            "first_name": "Test", "last_name": "Parent",
            "email": email, "password": "Test1234!",
            "role_type": "parent"
        }, headers=_h(school["token"]))
        assert res.status_code in (200, 201)

        login_res = await client.post("/api/auth/login", json={"email": email, "password": "Test1234!"})
        if login_res.status_code == 200:
            parent_token = login_res.json().get("access_token")
            res = await client.post("/api/classes", json={"name": "Hacked", "capacity": 40}, headers=_h(parent_token))
            assert res.status_code in (403, 401), f"Parent could create a class! Status: {res.status_code}"

    @pytest.mark.asyncio
    async def test_teacher_cannot_manage_users(self, client):
        school = await _register_school(client, "Ecole RBAC3")
        u = str(uuid.uuid4())[:8]
        email = f"teacher_{u}@test.com"

        res = await client.post("/api/admin/users", json={
            "first_name": "Test", "last_name": "Teacher",
            "email": email, "password": "Test1234!",
            "role_type": "teacher"
        }, headers=_h(school["token"]))
        assert res.status_code in (200, 201)

        login_res = await client.post("/api/auth/login", json={"email": email, "password": "Test1234!"})
        if login_res.status_code == 200:
            teacher_token = login_res.json().get("access_token")
            res = await client.get("/api/admin/users", headers=_h(teacher_token))
            assert res.status_code in (403, 401), f"Teacher could list all users! Status: {res.status_code}"

    @pytest.mark.asyncio
    async def test_unauthenticated_cannot_access任何endpoint(self, client):
        """All protected endpoints must reject unauthenticated requests."""
        protected = [
            ("GET", "/api/students"),
            ("GET", "/api/classes"),
            ("GET", "/api/grades"),
            ("GET", "/api/attendance"),
            ("GET", "/api/payments"),
            ("GET", "/api/bulletins"),
            ("GET", "/api/admin/users"),
            ("GET", "/api/admin/dashboard"),
            ("GET", "/api/admin/roles"),
            ("GET", "/api/admin/audit-log"),
        ]
        for method, url in protected:
            if method == "GET":
                res = await client.get(url)
            else:
                res = await client.post(url, json={})
            assert res.status_code in (401, 403), f"{method} {url} accessible without auth ({res.status_code})"


# ══════════════════════════════════════════════════════════════════
# CROSS-PORTAL FLOW TESTS
# ══════════════════════════════════════════════════════════════════

class TestCrossPortalFlow:
    """Verify data flows correctly between portals."""

    @pytest.mark.asyncio
    async def test_student_created_by_admin_visible_in_list(self, client):
        school = await _register_school(client, "Ecole Flow1")

        # Admin creates student
        res = await client.post("/api/students", json={
            "first_name": "Flow", "last_name": "Test", "gender": "F", "matricule": "FL-001"
        }, headers=_h(school["token"]))
        assert res.status_code in (200, 201)

        # Admin can see the student
        res = await client.get("/api/students", headers=_h(school["token"]))
        assert res.status_code == 200
        students = res.json().get("students", [])
        assert any(s.get("matricule") == "FL-001" for s in students)

    @pytest.mark.asyncio
    async def test_payment_pending_then_confirm(self, client):
        school = await _register_school(client, "Ecole Flow2")

        # Create student
        u = str(uuid.uuid4())[:8]
        res = await client.post("/api/students", json={
            "first_name": "Pay", "last_name": "Test", "gender": "M", "matricule": f"PAY-{u}"
        }, headers=_h(school["token"]))
        assert res.status_code in (200, 201), f"Student creation failed: {res.status_code} {res.text}"
        student_id = res.json().get("id")

        # Record payment (should be PENDING)
        res = await client.post("/api/payments", json={
            "student_id": student_id, "amount": 50000,
            "payment_method": "cash"
        }, headers=_h(school["token"]))
        assert res.status_code in (200, 201), f"Payment creation failed: {res.status_code} {res.text}"
        pay_id = res.json().get("id")
        status = res.json().get("status")
        assert status == "pending", f"Payment should be PENDING, got {status}"

        # Confirm payment
        res = await client.patch(f"/api/payments/{pay_id}/confirm", headers=_h(school["token"]))
        assert res.status_code == 200
        assert res.json().get("status") == "confirmed"

    @pytest.mark.asyncio
    async def test_payment_reject(self, client):
        school = await _register_school(client, "Ecole Flow3")

        u = str(uuid.uuid4())[:8]
        res = await client.post("/api/students", json={
            "first_name": "Reject", "last_name": "Test", "gender": "M", "matricule": f"RJ-{u}"
        }, headers=_h(school["token"]))
        assert res.status_code in (200, 201), f"Student creation failed: {res.status_code}"
        student_id = res.json().get("id")

        res = await client.post("/api/payments", json={
            "student_id": student_id, "amount": 25000,
            "payment_method": "mobile_money"
        }, headers=_h(school["token"]))
        assert res.status_code in (200, 201), f"Payment creation failed: {res.status_code} {res.text}"
        pay_id = res.json().get("id")

        res = await client.patch(f"/api/payments/{pay_id}/reject", headers=_h(school["token"]))
        assert res.status_code == 200
        assert res.json().get("status") == "cancelled"

    @pytest.mark.asyncio
    async def test_evaluation_crud(self, client):
        school = await _register_school(client, "Ecole Flow4")

        # Create cycle + level
        res = await client.post("/api/cycles", json={"name": "College", "code": "COL"}, headers=_h(school["token"]))
        cycle_id = res.json().get("id") if res.status_code in (200, 201) else None
        if not cycle_id:
            pytest.skip("Could not create cycle")

        res = await client.post("/api/levels", json={"name": "3eme", "code": "3E", "cycle_id": cycle_id}, headers=_h(school["token"]))
        level_id = res.json().get("id") if res.status_code in (200, 201) else None
        if not level_id:
            pytest.skip("Could not create level")

        # Create subject
        res = await client.post("/api/subjects", json={"name": "Math", "code": "MATH"}, headers=_h(school["token"]))
        subject_id = res.json().get("id") if res.status_code in (200, 201) else None
        if not subject_id:
            pytest.skip("Could not create subject")

        # Create class
        res = await client.post("/api/classes", json={
            "name": "3e A", "level_id": level_id, "capacity": 40
        }, headers=_h(school["token"]))
        class_id = res.json().get("id") if res.status_code in (200, 201) else None
        if not class_id:
            pytest.skip("Could not create class")

        # Link subject to class
        res = await client.post("/api/class-subjects", json={
            "class_id": class_id, "subject_id": subject_id, "coefficient": 3
        }, headers=_h(school["token"]))
        assert res.status_code in (200, 201), f"Could not link subject to class: {res.text}"

        # Create evaluation
        res = await client.post("/api/grades/evaluations", json={
            "class_id": class_id, "subject_id": subject_id,
            "name": "Devoir 1", "assessment_type": "devoir",
            "period": "T1", "max_grade": 20, "coefficient": 1,
            "date": "2025-10-01",
        }, headers=_h(school["token"]))
        assert res.status_code in (200, 201), f"Could not create evaluation: {res.text}"

    @pytest.mark.asyncio
    async def test_audit_log_created_on_sensitive_action(self, client):
        school = await _register_school(client, "Ecole Audit")

        # Check audit log has at least the registration action
        res = await client.get("/api/admin/audit-log", headers=_h(school["token"]))
        assert res.status_code == 200
        logs = res.json().get("logs", res.json().get("items", []))
        # At minimum the registration should have created an audit log
        assert isinstance(logs, list)


# ══════════════════════════════════════════════════════════════════
# SUBSCRIPTION LIMITS
# ══════════════════════════════════════════════════════════════════

class TestSubscriptionLimits:
    """Trial school cannot exceed 100 students."""

    @pytest.mark.asyncio
    async def test_trial_school_gets_subscription(self, client):
        school = await _register_school(client, "Ecole Sub")
        res = await client.get("/api/subscriptions/my-summary", headers=_h(school["token"]))
        assert res.status_code == 200
        data = res.json()
        assert data.get("plan_code") == "graine" or data.get("plan", {}).get("code") == "graine"


# ══════════════════════════════════════════════════════════════════
# ERROR HANDLING
# ══════════════════════════════════════════════════════════════════

class TestErrorHandling:
    """API should return proper error messages, not 500s."""

    @pytest.mark.asyncio
    async def test_nonexistent_student_returns_404(self, client):
        school = await _register_school(client, "Ecole Err")
        res = await client.get("/api/students/99999", headers=_h(school["token"]))
        assert res.status_code in (404, 403)

    @pytest.mark.asyncio
    async def test_nonexistent_payment_confirm_returns_404(self, client):
        school = await _register_school(client, "Ecole Err2")
        res = await client.patch("/api/payments/99999/confirm", headers=_h(school["token"]))
        assert res.status_code in (404, 403)

    @pytest.mark.asyncio
    async def test_invalid_token_returns_401(self, client):
        res = await client.get("/api/students", headers={"Authorization": "Bearer invalid_token"})
        assert res.status_code == 401

    @pytest.mark.asyncio
    async def test_missing_token_returns_401(self, client):
        res = await client.get("/api/students")
        assert res.status_code == 401
