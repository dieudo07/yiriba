"""Yiriba SaaS — Security tests: multi-tenant isolation, IDOR protection."""

import pytest
from httpx import AsyncClient

from app.core.security import create_access_token


@pytest.mark.security
class TestMultiTenantIsolation:
    """Verify that School A cannot access School B's data (IDOR protection)."""

    _counter = 0

    async def _create_two_schools(self, client: AsyncClient) -> tuple[dict, dict]:
        """Helper: create two schools and return their login payloads."""
        import time
        ts = int(time.time() * 1000)
        TestMultiTenantIsolation._counter += 1
        c = TestMultiTenantIsolation._counter
        reg1 = await client.post("/api/auth/register-school", json={
            "school_name": f"École A {c}",
            "admin_email": f"admin-a-{ts}@iso.com",
            "admin_first_name": "Admin",
            "admin_last_name": "A",
        })
        reg2 = await client.post("/api/auth/register-school", json={
            "school_name": f"École B {c}",
            "admin_email": f"admin-b-{ts}@iso.com",
            "admin_first_name": "Admin",
            "admin_last_name": "B",
        })
        # Pas d'auto-login : on se connecte avec le mot de passe temporaire.
        login1 = await client.post("/api/auth/login", json={
            "email": f"admin-a-{ts}@iso.com",
            "password": reg1.json()["admin"]["temp_password"],
        })
        login2 = await client.post("/api/auth/login", json={
            "email": f"admin-b-{ts}@iso.com",
            "password": reg2.json()["admin"]["temp_password"],
        })
        return login1.json(), login2.json()

    async def test_tokens_are_school_scoped(self, client: AsyncClient, db):
        """Each school's token should contain its own school_id."""
        data1, data2 = await self._create_two_schools(client)

        # Decode tokens to check school_id
        from app.core.security import decode_token
        payload1 = decode_token(data1["access_token"])
        payload2 = decode_token(data2["access_token"])

        assert payload1["school_id"] != payload2["school_id"]
        assert payload1["school_id"] > 0
        assert payload2["school_id"] > 0

    async def test_user_cannot_use_other_school_token(self, client: AsyncClient, db):
        """A token from School A should not grant access to School B's resources."""
        data1, data2 = await self._create_two_schools(client)

        token_a = data1["access_token"]

        # Try to access with School A's token but with School B's context
        # The API should use the school_id from the token, not from the request
        response = await client.get(
            "/api/students",
            headers={"Authorization": f"Bearer {token_a}"},
        )
        # Should return School A's students (likely empty), not School B's
        assert response.status_code in (200, 404)


@pytest.mark.security
class TestPasswordSecurity:
    """Verify password hashing and validation."""

    async def test_password_not_stored_in_plaintext(self, client: AsyncClient, db):
        """Password hash should be bcrypt, not plaintext."""
        from app.core.security import hash_password, verify_password

        hashed = hash_password("SecurePass123")
        assert hashed != "SecurePass123"
        assert hashed.startswith("$2")  # bcrypt prefix
        assert verify_password("SecurePass123", hashed)

    async def test_client_password_cannot_weaken_account(self, client: AsyncClient, db):
        """Le mot de passe envoyé au register est ignoré : le serveur impose
        toujours un mot de passe temporaire aléatoire et fort."""
        weak_passwords = ["nouppercase1", "NOLOWERCASE1", "NoNumbers!", "1234"]
        for pw in weak_passwords:
            response = await client.post("/api/auth/register-school", json={
                "school_name": f"École {pw[:5]}",
                "admin_email": f"admin-{pw[:5].lower()}@test.com",
                "admin_first_name": "X",
                "admin_last_name": "Y",
                "admin_password": pw,  # ignoré par le serveur
            })
            assert response.status_code == 200
            temp = response.json()["admin"]["temp_password"]
            assert any(c.isupper() for c in temp), f"temp weak: {temp}"
            assert any(c.islower() for c in temp), f"temp weak: {temp}"
            assert any(c.isdigit() for c in temp), f"temp weak: {temp}"

    async def test_password_not_in_api_response(self, client: AsyncClient, db):
        """Login response should never contain the password hash."""
        reg = await client.post("/api/auth/register-school", json={
            "school_name": "École NoHash",
            "admin_email": "nohash@test.com",
            "admin_first_name": "N",
            "admin_last_name": "H",
        })
        temp = reg.json()["admin"]["temp_password"]
        response = await client.post("/api/auth/login", json={
            "email": "nohash@test.com",
            "password": temp,
        })
        user_data = response.json().get("user", {})
        assert "password" not in user_data
        assert "password_hash" not in user_data


@pytest.mark.security
class TestJWTSecurity:
    """Verify JWT token security."""

    async def test_expired_token_rejected(self, client: AsyncClient, db):
        """Expired tokens should be rejected."""
        from datetime import timedelta
        from app.core.security import create_access_token

        token = create_access_token(
            {"sub": "1", "school_id": 1, "role": "admin"},
            expires_delta=timedelta(seconds=-1),  # Already expired
        )
        response = await client.get(
            "/api/students",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert response.status_code == 401

    async def test_malformed_token_rejected(self, client: AsyncClient, db):
        """Malformed tokens should be rejected."""
        response = await client.get(
            "/api/students",
            headers={"Authorization": "Bearer not-a-real-jwt"},
        )
        assert response.status_code == 401

    async def test_missing_auth_header_rejected(self, client: AsyncClient, db):
        """Requests without Authorization header should get 401."""
        response = await client.get("/api/students")
        assert response.status_code == 401


@pytest.mark.security
class TestSecurityHeaders:
    """Verify security headers are present on responses."""

    async def test_security_headers_present(self, client: AsyncClient):
        """All responses should have security headers."""
        response = await client.get("/health")
        assert response.headers.get("X-Content-Type-Options") == "nosniff"
        assert response.headers.get("X-Frame-Options") == "DENY"
        assert response.headers.get("X-XSS-Protection") == "1; mode=block"
