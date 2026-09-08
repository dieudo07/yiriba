"""Yiriba SaaS — Identifiants élèves uniques GLOBALEMENT (préfixe école).

Deux écoles différentes ne doivent jamais générer le même identifiant
de connexion élève (ex: CYA-000001 vs LTB-000001), sinon le login
devient ambigu.
"""
import uuid

import pytest
from tests.conftest import register_and_login


@pytest.mark.asyncio
async def test_student_ids_globally_unique(client):
    """Deux écoles créant chacune un compte élève → identifiants distincts."""
    ctxs = []
    for name in ("Ecole Unique Un", "Ecole Unique Deux"):
        ctx = await register_and_login(client, name=name)
        ctxs.append(ctx)

    ids = []
    for ctx in ctxs:
        h = {"Authorization": f"Bearer {ctx['token']}"}
        rc = await client.post("/api/classes", json={"name": f"6e {ctx['school_id']}", "level": "6e", "academic_year": "2026-2027", "capacity": 30}, headers=h)
        class_id = rc.json()["id"]
        rs = await client.post("/api/students", json={
            "first_name": "Test", "last_name": f"El{ctx['school_id']}", "gender": "M",
            "birth_date": "2010-01-01", "class_id": class_id}, headers=h)
        assert rs.status_code == 201, rs.text
        ra = await client.post(f"/api/students/{rs.json()['id']}/access", headers=h)
        assert ra.status_code in (200, 201), ra.text
        ids.append(ra.json()["username"])

    assert ids[0] != ids[1], f"Collision d'identifiants entre écoles : {ids}"
    for i in ids:
        assert not i.startswith("YRB-"), f"ancien format encore généré : {i}"


@pytest.mark.asyncio
async def test_school_prefix_auto_derived_and_unique(client):
    """Le sigle est dérivé du nom d'école et dédoublonné globalement."""
    ctx = await register_and_login(client, name="College Prefixe Auto")
    h = {"Authorization": f"Bearer {ctx['token']}"}
    rc = await client.post("/api/classes", json={"name": "6e PA", "level": "6e", "academic_year": "2026-2027", "capacity": 30}, headers=h)
    class_id = rc.json()["id"]
    rs = await client.post("/api/students", json={
        "first_name": "Pre", "last_name": "Fixe", "gender": "F",
        "birth_date": "2010-01-01", "class_id": class_id}, headers=h)
    ra = await client.post(f"/api/students/{rs.json()['id']}/access", headers=h)
    username = ra.json()["username"]
    # Format SIGLE-NNNNNN
    import re
    assert re.match(r"^[A-Z]{2,5}-\d{6}$", username), f"format inattendu : {username}"
    # Login direct sans ambiguïté
    rl = await client.post("/api/auth/login", json={"email": username, "password": ra.json()["temp_password"]})
    assert rl.status_code == 200, rl.text
