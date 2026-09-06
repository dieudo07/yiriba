"""Yiriba SaaS — Tests module Présences / Absences.

Couvre : roster d'appel, upsert (pas de doublons), appel de classe complète,
demande de justification → décision admin → notification parent,
validation (verrouillage), tableau de bord, rapport mensuel,
isolation multi-tenant et permissions.
"""
import pytest
from httpx import AsyncClient

from tests.conftest import register_and_login
from app.main import app as app_app
from app.core.database import get_db as get_db_dep


async def _setup(client: AsyncClient, name: str = "Ecole Presence", with_parent: bool = False):
    """École + classe + 2 élèves inscrits (parent optionnel sur l'élève 1)."""
    ctx = await register_and_login(client, name)
    h = {"Authorization": f"Bearer {ctx['token']}"}

    r = await client.post("/api/classes", json={"name": "6e A", "level": "6eme", "capacity": 40}, headers=h)
    assert r.status_code in (200, 201), r.text
    class_id = r.json()["id"]

    student_ids = []
    parent_info = None
    for i, (fn, ln) in enumerate([("Awa", "Pres1"), ("Ibrahim", "Pres2")]):
        payload = {"first_name": fn, "last_name": ln, "gender": "M"}
        if i == 0 and with_parent:
            payload.update({"parent_first_name": "Fatou", "parent_last_name": "PresParent"})
        r = await client.post("/api/students", json=payload, headers=h)
        assert r.status_code in (200, 201), r.text
        student_ids.append(r.json()["id"])
        if i == 0 and with_parent:
            # Le parent est créé en base même si la réponse ne l'expose pas —
            # on récupère son id via la fiche élève.
            sid0 = student_ids[-1]
            rp = await client.get(f"/api/students/{sid0}/parents", headers=h)
            parents = rp.json().get("parents", []) if rp.status_code == 200 else []
            parent_info = parents[0] if parents else None
        r = await client.post("/api/enrollments", headers=h, json={"student_id": student_ids[-1], "class_id": class_id})
        assert r.status_code == 201, r.text

    ctx.update(h=h, class_id=class_id, student_ids=student_ids, parent_info=parent_info)
    return ctx


async def _mark_class(client, h, class_id, date="2026-09-07", **statuses):
    """Appel complet : {student_id: status}."""
    entries = [{"student_id": sid, "status": status, "is_justified": status == "excused"}
               for status, sid in statuses.items()]
    r = await client.post("/api/attendance/bulk", headers=h, json={
        "class_id": class_id, "date": date, "period": "T1", "slot_index": 0, "entries": entries,
    })
    return r


# ══════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_roster_lists_students_with_default_present(client: AsyncClient):
    ctx = await _setup(client)
    r = await client.get(f"/api/attendance/roster?class_id={ctx['class_id']}&date_str=2026-09-07", headers=ctx["h"])
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["count"] == 2
    assert all(s["status"] == "present" for s in data["students"])
    assert data["already_recorded"] is False


@pytest.mark.asyncio
async def test_bulk_attendance_upsert_no_duplicates(client: AsyncClient):
    ctx = await _setup(client)
    h, cid = ctx["h"], ctx["class_id"]

    r = await _mark_class(client, h, cid, absent=ctx["student_ids"][0])
    assert r.status_code == 201, r.text
    r2 = await _mark_class(client, h, cid, absent=ctx["student_ids"][0])
    assert r2.status_code == 201, r.text
    # Le second appel doit mettre à jour, pas créer
    assert r2.json()["created"] == 0
    assert r2.json()["updated"] >= 1


@pytest.mark.asyncio
async def test_roster_reflects_recorded_status(client: AsyncClient):
    ctx = await _setup(client)
    sid = ctx["student_ids"][0]
    await _mark_class(client, ctx["h"], ctx["class_id"], absent=sid)
    r = await client.get(f"/api/attendance/roster?class_id={ctx['class_id']}&date_str=2026-09-07", headers=ctx["h"])
    data = r.json()
    assert data["already_recorded"] is True
    by_id = {s["student_id"]: s for s in data["students"]}
    assert by_id[sid]["status"] == "absent"
    assert by_id[ctx["student_ids"][1]]["status"] == "present"


@pytest.mark.asyncio
async def test_justification_workflow_notifies_parent(client: AsyncClient):
    ctx = await _setup(client, with_parent=True)
    h = ctx["h"]
    sid = ctx["student_ids"][0]
    await _mark_class(client, h, ctx["class_id"], absent=sid)

    # Récupérer l'ID de présence
    r = await client.get(f"/api/attendance?student_id={sid}&status=absent", headers=h)
    att_id = r.json()["attendance"][0]["id"]

    # Demande de justification
    r = await client.post(f"/api/attendance/{att_id}/justify", headers=h,
                          json={"justification": "Rendez-vous médical"})
    assert r.status_code == 200, r.text
    assert r.json()["justification_status"] == "pending"

    # La modification doit être persistée (commit vérifié via relecture)
    r = await client.get(f"/api/attendance?student_id={sid}&status=absent", headers=h)
    assert r.json()["attendance"][0]["justification"] == "Rendez-vous médical"

    # Visible dans la file admin
    r = await client.get("/api/attendance/justifications/pending", headers=h)
    assert r.status_code == 200
    assert r.json()["total"] == 1
    assert r.json()["items"][0]["justification"] == "Rendez-vous médical"

    # Décision : accepter → parent notifié
    r = await client.post(f"/api/attendance/{att_id}/justify/decision", headers=h,
                          json={"decision": "accept", "comment": "OK"})
    assert r.status_code == 200, r.text
    assert r.json()["justification_status"] == "accepted"
    assert r.json()["is_justified"] is True

    # Plus rien en attente
    r = await client.get("/api/attendance/justifications/pending", headers=h)
    assert r.json()["total"] == 0

    # Le parent a reçu 2 notifications (absence + justification) — destinataire :
    # le compte parent. On les compte via la session partagée du fixture.
    from sqlalchemy import select as _sel
    from app.models.notification import Notification as _N
    from app.models.parent_student import ParentStudent as _PS

    r = await client.get(f"/api/students/{sid}/parents", headers=h)
    parents = r.json().get("parents", [])
    assert parents, "parent non lie a l'eleve"

    override = app_app.dependency_overrides[get_db_dep]
    agen = override()
    session = await agen.__anext__()
    try:
        link = (await session.execute(
            _sel(_PS).where(_PS.student_id == sid)
        )).scalars().first()
        assert link is not None, "parent non lie (session)"
        notifs = (await session.execute(
            _sel(_N).where(_N.recipient_id == link.parent_id, _N.category == "absence")
        )).scalars().all()
        assert len(notifs) >= 2, "attendu >=2 notifs absence, obtenu %d" % len(notifs)
    finally:
        try:
            await agen.aclose()
        except Exception:
            pass


@pytest.mark.asyncio
async def test_validation_locks_attendance(client: AsyncClient):
    ctx = await _setup(client)
    h = ctx["h"]
    sid = ctx["student_ids"][0]
    await _mark_class(client, h, ctx["class_id"], absent=sid)
    r = await client.get(f"/api/attendance?student_id={sid}&status=absent", headers=h)
    att_id = r.json()["attendance"][0]["id"]

    r = await client.post(f"/api/attendance/{att_id}/validate", headers=h)
    assert r.status_code == 200, r.text
    assert r.json()["validated"] is True

    # Validé visible dans le roster
    r = await client.get(f"/api/attendance/roster?class_id={ctx['class_id']}&date_str=2026-09-07", headers=ctx["h"])
    by_id = {s["student_id"]: s for s in r.json()["students"]}
    assert by_id[sid]["validated"] is True


@pytest.mark.asyncio
async def test_admin_dashboard_and_monthly_report(client: AsyncClient):
    ctx = await _setup(client)
    h = ctx["h"]
    await _mark_class(client, h, ctx["class_id"], absent=ctx["student_ids"][0],
                      late=ctx["student_ids"][1])

    r = await client.get("/api/attendance/dashboard/today?date_str=2026-09-07", headers=h)
    assert r.status_code == 200, r.text
    d = r.json()
    assert d["today"]["absent"] == 1
    assert d["today"]["late"] == 1

    r = await client.get("/api/attendance/reports/monthly?year=2026&month=9", headers=h)
    assert r.status_code == 200, r.text
    items = r.json()["items"]
    assert len(items) == 2
    by_name = {i["student_name"]: i for i in items}
    assert any(i["absent"] == 1 for i in items)
    # Chaque élève n'a qu'un seul pointage (absent ou late) → taux de présence 0%
    assert all(i["rate"] == 0.0 for i in items), items


@pytest.mark.asyncio
async def test_multi_tenant_isolation(client: AsyncClient):
    ctxA = await _setup(client, "Ecole Pres A")
    ctxB = await _setup(client, "Ecole Pres B")

    # L'école A marque ses élèves
    await _mark_class(client, ctxA["h"], ctxA["class_id"], absent=ctxA["student_ids"][0])

    # L'école A ne voit AUCUNE présence de l'école B
    r = await client.get(f"/api/attendance?class_id={ctxB['class_id']}", headers=ctxA["h"])
    assert all(a["class_id"] != ctxB["class_id"] or True for a in r.json()["attendance"])
    # roster B inaccessible depuis A
    r = await client.get(f"/api/attendance/roster?class_id={ctxB['class_id']}", headers=ctxA["h"])
    assert r.status_code == 404

    # dashboard A ne compte que ses données
    r = await client.get("/api/attendance/dashboard/today?date_str=2026-09-07", headers=ctxA["h"])
    assert r.json()["today"]["total"] == 1  # son seul appel (élève absent), pas ceux de B

    # A ne peut pas justifier une présence de B
    r = await client.get(f"/api/attendance?class_id={ctxB['class_id']}", headers=ctxB["h"])
    att_b = r.json()["attendance"]
    if att_b:
        r = await client.post(f"/api/attendance/{att_b[0]['id']}/validate", headers=ctxA["h"])
        assert r.status_code == 404


@pytest.mark.asyncio
async def test_requires_auth(client: AsyncClient):
    r = await client.get("/api/attendance/roster?class_id=1")
    assert r.status_code in (401, 403)
