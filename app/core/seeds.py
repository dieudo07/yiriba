"""Yiriba SaaS — Seeds for permissions and default roles."""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.permission import Permission, Role, RolePermission

# ── 39 Permissions atomiques ──────────────────────────────────────

PERMISSIONS_SEED: list[tuple[str, str, str, str]] = [
    # Élèves
    ("student.create",  "student",   "create",  "Créer un élève"),
    ("student.read",    "student",   "read",    "Consulter les élèves"),
    ("student.update",  "student",   "update",  "Modifier un élève"),
    ("student.delete",  "student",   "delete",  "Supprimer un élève"),
    ("student.import",  "student",   "import",  "Importer des élèves (CSV)"),
    # Notes
    ("grade.create",    "grade",     "create",  "Saisir des notes"),
    ("grade.read",      "grade",     "read",    "Consulter les notes"),
    ("grade.update",    "grade",     "update",  "Modifier une note"),
    ("grade.delete",    "grade",     "delete",  "Supprimer une note"),
    # Paiements
    ("payment.create",  "payment",   "create",  "Enregistrer un paiement"),
    ("payment.read",    "payment",   "read",    "Consulter les paiements"),
    ("payment.update",  "payment",   "update",  "Modifier un paiement"),
    ("payment.delete",  "payment",   "delete",  "Supprimer un paiement"),
    ("payment.refund",  "payment",   "refund",  "Rembourser un paiement"),
    # Bulletins
    ("bulletin.generate", "bulletin", "generate", "Générer des bulletins"),
    ("bulletin.read",     "bulletin", "read",     "Consulter les bulletins"),
    # Classes
    ("class.create",    "class",     "create",  "Créer une classe"),
    ("class.read",      "class",     "read",    "Consulter les classes"),
    ("class.update",    "class",     "update",  "Modifier une classe"),
    ("class.delete",    "class",     "delete",  "Supprimer une classe"),
    ("class.manage",    "class",     "manage",  "Gerer les classes (liaisons matieres)"),
    # Enseignants
    ("teacher.create",  "teacher",   "create",  "Créer un enseignant"),
    ("teacher.read",    "teacher",   "read",    "Consulter les enseignants"),
    ("teacher.update",  "teacher",   "update",  "Modifier un enseignant"),
    ("teacher.delete",  "teacher",   "delete",  "Supprimer un enseignant"),
    # Utilisateurs
    ("user.create",     "user",      "create",  "Créer un utilisateur"),
    ("user.read",       "user",      "read",    "Consulter les utilisateurs"),
    ("user.update",     "user",      "update",  "Modifier un utilisateur"),
    ("user.delete",     "user",      "delete",  "Supprimer un utilisateur"),
    ("user.validate",   "user",      "validate", "Valider un compte utilisateur"),
    # Rôles
    ("role.create",     "role",      "create",  "Créer un rôle personnalisé"),
    ("role.read",       "role",      "read",    "Consulter les rôles"),
    ("role.update",     "role",      "update",  "Modifier un rôle personnalisé"),
    ("role.delete",     "role",      "delete",  "Supprimer un rôle personnalisé"),
    # Paramètres
    ("settings.manage", "settings",  "manage",  "Gérer les paramètres"),
    # Audit
    ("audit.read",      "audit",     "read",    "Consulter l'audit trail"),
    # Emploi du temps
    ("timetable.manage","timetable", "manage",  "Gérer l'emploi du temps"),
    # Présences
    ("attendance.create","attendance","create",  "Pointer les présences"),
    ("attendance.read",  "attendance","read",    "Consulter les présences"),
    ("attendance.update","attendance","update",  "Valider / modifier les présences"),
    ("attendance.justify","attendance","justify","Accepter ou refuser les justifications"),
    # Discipline
    ("discipline.read",   "discipline", "read",    "Consulter les incidents disciplinaires"),
    ("discipline.create", "discipline", "create",  "Enregistrer un incident"),
    ("discipline.update", "discipline", "update",  "Modifier un incident"),
    ("discipline.delete", "discipline", "delete",  "Annuler un incident"),
    ("discipline.manage", "discipline", "manage",  "Configurer les règles disciplinaires"),
    # Messagerie
    ("message.send",     "message",   "send",     "Envoyer des messages"),
    ("message.read",     "message",   "read",     "Lire les messages"),
    ("message.audit",    "message",   "audit",    "Consulter les conversations (supervision)"),
    # Rapports
    ("report.read",     "report",    "read",    "Consulter les rapports"),
    # Evaluation (nouveau module)
    ("evaluation.create","evaluation","create",  "Creer des evaluations"),
    ("evaluation.read",  "evaluation","read",    "Consulter les evaluations"),
    ("evaluation.update", "evaluation","update",  "Modifier une evaluation"),
    ("evaluation.delete", "evaluation","delete",  "Supprimer une evaluation"),
    # Bulletin override
    ("bulletin.override", "bulletin", "override", "Modifier un bulletin publie"),
    # Notifications
    ("notification.manage","notification","manage", "Gerer les notifications"),
]

# ── Rôles système par école ──────────────────────────────────────

DEFAULT_ROLE_DEFINITIONS: dict[str, list[str]] = {
    "Directeur": [
        # Tout
        "student.create", "student.read", "student.update", "student.delete", "student.import",
        "grade.create", "grade.read", "grade.update", "grade.delete",
        "payment.create", "payment.read", "payment.update", "payment.delete", "payment.refund",
        "bulletin.generate", "bulletin.read",
        "class.create", "class.read", "class.update", "class.delete", "class.manage",
        "teacher.create", "teacher.read", "teacher.update", "teacher.delete",
        "user.create", "user.read", "user.update", "user.delete", "user.validate",
        "role.create", "role.read", "role.update", "role.delete",
        "settings.manage",
        "audit.read",
        "timetable.manage",
        "attendance.create", "attendance.read", "attendance.update", "attendance.justify",
        "discipline.read", "discipline.create", "discipline.update", "discipline.delete", "discipline.manage",
        "report.read",
        "evaluation.create", "evaluation.read", "evaluation.update", "evaluation.delete",
        "bulletin.override",
        "notification.manage",
        "message.send", "message.read", "message.audit",
    ],
    "Comptable": [
        "payment.create", "payment.read", "payment.update",
        "student.read",
        "bulletin.read",
        "report.read",
        "message.send", "message.read",
    ],
    "Secrétaire": [
        "student.create", "student.read", "student.update",
        "class.read",
        "teacher.read",
        "attendance.create", "attendance.read",
        "bulletin.read",
        "message.send", "message.read",
    ],
    "Enseignant": [
        "grade.create", "grade.read", "grade.update",
        "attendance.create", "attendance.read",
        "discipline.read", "discipline.create",
        "student.read",
        "evaluation.create", "evaluation.read", "evaluation.update",
        "class.read",
        "bulletin.read",
        "message.send", "message.read",
    ],
    "Parent": [
        "student.read",
        "grade.read",
        "attendance.read",
        "bulletin.read",
        "payment.read",
        "message.send", "message.read",
    ],
    "Élève": [
        "grade.read",
        "bulletin.read",
        "attendance.read",
    ],
}


async def seed_permissions(db: AsyncSession) -> None:
    """Create all 39 permissions if they don't exist. Called at app startup."""
    existing = await db.execute(select(Permission.codename))
    existing_names = {row[0] for row in existing.all()}

    for codename, resource, action, description in PERMISSIONS_SEED:
        if codename not in existing_names:
            db.add(Permission(
                codename=codename,
                resource=resource,
                action=action,
                description=description,
            ))

    await db.commit()


async def seed_school_roles(db: AsyncSession, school_id: int) -> dict[str, Role]:
    """Create default system roles for a new school. Called after school creation.

    Returns a dict {role_name: Role} for convenience.
    """
    # Load all permissions
    result = await db.execute(select(Permission))
    all_permissions = {p.codename: p for p in result.scalars().all()}

    created_roles: dict[str, Role] = {}

    for role_name, permission_codenames in DEFAULT_ROLE_DEFINITIONS.items():
        # Check if role already exists for this school
        existing = await db.execute(
            select(Role).where(Role.school_id == school_id, Role.name == role_name)
        )
        if existing.scalar_one_or_none():
            continue

        role = Role(
            school_id=school_id,
            name=role_name,
            is_system=True,
        )
        db.add(role)
        await db.flush()

        for codename in permission_codenames:
            perm = all_permissions.get(codename)
            if perm is None:
                raise ValueError(f"Permission seed manquante : {codename}")
            db.add(RolePermission(role_id=role.id, permission_id=perm.id))

        created_roles[role_name] = role

    await db.commit()
    return created_roles


# ── Plans d'abonnement YIRIBA ─────────────────────────────────────

DEFAULT_SUBSCRIPTION_PLANS = [
    {
        "name": "Graine",
        "code": "graine",
        "max_students": 100,
        "trial_days": 90,
        "price_per_student_year": "650.00",
        "features": '{"students": true, "classes": true, "subjects": true, "grades": true, "attendance": true, "bulletins": true, "payments": true, "parents": true, "reports": true, "advanced_reports": false, "multi_campus": false, "api": false, "priority_support": false}',
    },
    {
        "name": "Racine",
        "code": "racine",
        "max_students": 400,
        "trial_days": 0,
        "price_per_student_year": "600.00",
        "features": '{"students": true, "classes": true, "subjects": true, "grades": true, "attendance": true, "bulletins": true, "payments": true, "parents": true, "reports": true, "advanced_reports": true, "multi_campus": false, "api": false, "priority_support": false}',
    },
    {
        "name": "Baobab",
        "code": "baobab",
        "max_students": None,
        "trial_days": 0,
        "price_per_student_year": "0.00",
        "features": '{"students": true, "classes": true, "subjects": true, "grades": true, "attendance": true, "bulletins": true, "payments": true, "parents": true, "reports": true, "advanced_reports": true, "multi_campus": true, "api": true, "priority_support": true}',
    },
]


async def seed_subscription_plans(db: AsyncSession) -> None:
    """Create the 3 default YIRIBA subscription plans if they don't exist."""
    from app.models.subscription import SubscriptionPlan

    existing = await db.execute(select(SubscriptionPlan.code))
    existing_codes = {row[0] for row in existing.all()}

    for plan_data in DEFAULT_SUBSCRIPTION_PLANS:
        if plan_data["code"] not in existing_codes:
            db.add(SubscriptionPlan(
                name=plan_data["name"],
                code=plan_data["code"],
                max_students=plan_data["max_students"],
                trial_days=plan_data["trial_days"],
                price_per_student_year=plan_data["price_per_student_year"],
                features=plan_data["features"],
                is_active=True,
            ))

    await db.commit()


# ── Backfill roles for existing schools ──────────────────────────


async def backfill_roles_for_existing_schools(db: AsyncSession) -> None:
    """Ensure all existing schools have the complete set of system roles.

    Called at startup to handle role additions (Enseignant, Parent, Élève).
    """
    from app.models.school import School

    # Load all permissions
    result = await db.execute(select(Permission))
    all_permissions = {p.codename: p for p in result.scalars().all()}

    # Get all schools
    schools_result = await db.execute(select(School.id))
    school_ids = [row[0] for row in schools_result.all()]

    for school_id in school_ids:
        for role_name, permission_codenames in DEFAULT_ROLE_DEFINITIONS.items():
            # Check if role already exists
            existing = await db.execute(
                select(Role).where(Role.school_id == school_id, Role.name == role_name)
            )
            role = existing.scalar_one_or_none()
            if role is None:
                # Create missing role
                role = Role(school_id=school_id, name=role_name, is_system=True)
                db.add(role)
                await db.flush()

            # Add any missing permissions to the role (never removes existing)
            existing_perm_ids = (await db.execute(
                select(RolePermission.permission_id).where(
                    RolePermission.role_id == role.id
                )
            )).scalars().all()
            existing_perm_set = set(existing_perm_ids)

            for codename in permission_codenames:
                perm = all_permissions.get(codename)
                if perm and perm.id not in existing_perm_set:
                    db.add(RolePermission(role_id=role.id, permission_id=perm.id))

    await db.commit()
