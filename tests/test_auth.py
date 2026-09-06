"""Yiriba SaaS — Authentication tests."""

import pytest
from httpx import AsyncClient

from app.core.security import hash_password
from app.models.user import User, UserStatus, UserRole
from app.models.school import School
from app.models.permission import Role


_REGISTER_PAYLOAD = {
    "school_name": "École Test",
    "admin_first_name": "Ibrahim",
    "admin_last_name": "Traoré",
    "admin_email": "directeur@test.com",
    "admin_password": "WhateverClientSends123",
}


async def _raw_register(client, **overrides):
    payload = {**_REGISTER_PAYLOAD, **overrides}
    return await client.post("/api/auth/register-school", json=payload)


@pytest.mark.integration
class TestRegistration:
    """Test school registration endpoint."""

    async def test_register_school_success(self, client: AsyncClient, db):
        """Registering a school returns a confirmation + temporary password,
        jamais de token (pas d'auto-login)."""
        response = await _raw_register(client, school_name="École Test Banfora")
        assert response.status_code == 200
        data = response.json()
        assert data.get("success") is True
        assert "access_token" not in data
        assert "refresh_token" not in data
        assert data["school"]["name"] == "École Test Banfora"
        temp = data["admin"]["temp_password"]
        assert len(temp) >= 12
        assert any(c.isupper() for c in temp) and any(c.isdigit() for c in temp)

    async def test_register_duplicate_email(self, client: AsyncClient, db):
        """Registering twice with the same email should fail with 409."""
        await _raw_register(client, school_name="École A", admin_email="admin@a.com")
        response = await _raw_register(
            client, school_name="École A 2", admin_email="admin@a.com"
        )
        assert response.status_code == 409

    async def test_register_ignores_client_password(self, client: AsyncClient, db):
        """Le mot de passe envoyé par le client est ignoré : le serveur
        génère un mot de passe temporaire aléatoire et fort."""
        response = await _raw_register(
            client, school_name="École B", admin_email="admin@b.com",
            admin_password="123",  # que le client le veuille ou non...
        )
        assert response.status_code == 200
        temp = response.json()["admin"]["temp_password"]
        assert any(c.isupper() for c in temp)
        assert any(c.islower() for c in temp)
        assert any(c.isdigit() for c in temp)


@pytest.mark.integration
class TestLogin:
    """Test login endpoint."""

    async def test_login_success(self, client: AsyncClient, db):
        """Login avec le mot de passe temporaire doit renvoyer des tokens."""
        reg = await _raw_register(client, school_name="École Login", admin_email="login@test.com")
        temp = reg.json()["admin"]["temp_password"]

        response = await client.post("/api/auth/login", json={
            "email": "login@test.com",
            "password": temp,
        })
        assert response.status_code == 200
        data = response.json()
        assert "access_token" in data
        assert data["user"]["email"] == "login@test.com"

    async def test_login_wrong_password(self, client: AsyncClient, db):
        """Login with wrong password should fail."""
        reg = await _raw_register(client, school_name="École Bad", admin_email="bad@test.com")
        temp = reg.json()["admin"]["temp_password"]
        assert temp != "WrongPassword999"

        response = await client.post("/api/auth/login", json={
            "email": "bad@test.com",
            "password": "WrongPassword999",
        })
        assert response.status_code == 401

    async def test_login_nonexistent_user(self, client: AsyncClient, db):
        """Login with non-existent email should fail."""
        response = await client.post("/api/auth/login", json={
            "email": "ghost@test.com",
            "password": "Whatever123",
        })
        assert response.status_code == 401


@pytest.mark.integration
class TestTokenRefresh:
    """Test token refresh endpoint."""

    async def test_refresh_success(self, client: AsyncClient, db):
        """Refresh token should return new access + refresh tokens."""
        reg = await _raw_register(client, school_name="École Refresh", admin_email="refresh@test.com")
        temp = reg.json()["admin"]["temp_password"]
        login = await client.post("/api/auth/login", json={
            "email": "refresh@test.com", "password": temp,
        })
        refresh = login.json()["refresh_token"]

        response = await client.post("/api/auth/refresh", json={
            "refresh_token": refresh,
        })
        assert response.status_code == 200
        assert "access_token" in response.json()

    async def test_refresh_invalid_token(self, client: AsyncClient, db):
        """Invalid refresh token should fail."""
        response = await client.post("/api/auth/refresh", json={
            "refresh_token": "invalid-token-here",
        })
        assert response.status_code == 401
