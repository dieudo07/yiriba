# 🌳 Yiriba SaaS — Gestion Scolaire Multi-établissement

SaaS de gestion scolaire pour le Burkina Faso. Sécurisé, mobile-first, multi-établissement.

## 🏗️ Architecture

```
FastAPI (Python 3.11+)
├── app/
│   ├── core/           # Config, DB, Security, Seeds
│   ├── models/         # SQLAlchemy ORM (11 tables)
│   ├── schemas/        # Pydantic validation
│   ├── routes/         # API endpoints
│   ├── services/       # Business logic (RBAC, ownership filter)
│   └── middleware/      # Security middleware
├── alembic/            # DB migrations
├── tests/              # pytest + async tests
└── static/             # Frontend (public.html, etc.)
```

### Stack technique

| Composant | Choix | Justification |
|-----------|-------|---------------|
| Backend | FastAPI | Validation Pydantic native, doc OpenAPI auto, async |
| DB | SQLite (dev) / PostgreSQL (prod) | RLS multi-tenant, chiffrement |
| Auth | JWT + Refresh Tokens | Access 15min, Refresh 7j, rotation |
| Hashing | bcrypt 12 rounds | OWASP recommandation |
| Tests | pytest + httpx | Async, fixtures, couverture 80%+ |
| Lint | ruff + mypy | Format + typage statique |

### Multi-tenant

- Chaque école est un **tenant** isolé
- `school_id` non-nullable sur TOUTES les tables métier
- JWT contient toujours `school_id` (jamais envoyé par le client)
- **RBAC** : 39 permissions atomiques × rôles personnalisables par école
- **OwnershipFilter** : Enseignant → ses classes, Parent → ses enfants

## 🚀 Quick Start

```bash
# 1. Cloner et entrer dans le dossier
cd YIRIBA_SAAS

# 2. Créer l'environnement virtuel
python -m venv .venv
.venv\Scripts\activate     # Windows
# source .venv/bin/activate  # Linux/Mac

# 3. Installer les dépendances
pip install -e ".[dev]"

# 4. Copier le fichier d'environnement
cp .env.example .env

# 5. Lancer le serveur
uvicorn app.main:app --reload --port 5050

# 6. Ouvrir la doc API
# → http://127.0.0.1:5050/docs
```

## 🧪 Tests

```bash
# Tous les tests
pytest

# Avec couverture
pytest --cov=app --cov-report=html

# Tests de sécurité uniquement
pytest -m security

# Tests d'intégration
pytest -m integration
```

## 📊 Base de données

### Tables (11 au total)

| Table | Description |
|-------|-------------|
| `schools` | Écoles (tenants) |
| `users` | Utilisateurs avec statut (pending/active/suspended) |
| `roles` | Rôles système + personnalisés |
| `permissions` | 39 permissions atomiques |
| `role_permissions` | Liaison rôle ↔ permission |
| `students` | Élèves |
| `classes` | Classes |
| `subjects` | Matières |
| `enrollments` | Inscriptions |
| `grades` | Notes (D/1, D/2, Comp.) |
| `attendances` | Présences/Absences/Retards |
| `payments` | Paiements |
| `fee_obligations` | Frais scolaires |
| `audit_logs` | Journal d'audit |
| `school_settings` | Paramètres par école |

### Permissions RBAC (39 atomiques)

| Resource | Actions |
|----------|---------|
| student | create, read, update, delete, import |
| grade | create, read, update, delete |
| payment | create, read, update, delete, refund |
| bulletin | generate, read |
| class | create, read, update, delete |
| teacher | create, read, update, delete |
| user | create, read, update, delete, validate |
| role | create, read, update, delete |
| settings | manage |
| audit | read |
| timetable | manage |
| attendance | create, read |
| report | read |

### Rôles système par école

| Rôle | Permissions |
|------|-------------|
| **Directeur** | Toutes (39) |
| **Comptable** | payment.*, student.read, bulletin.read, report.read |
| **Secrétaire** | student.*, class.read, teacher.read, attendance.*, bulletin.read |

→ Le directeur peut créer des **rôles personnalisés** au-delà de ces 3.

## 🔒 Sécurité

- [x] JWT avec access token (15min) + refresh token (7j, rotation)
- [x] bcrypt 12 rounds pour tous les mots de passe
- [x] RBAC centralisé (39 permissions × rôles)
- [x] OwnershipFilter (enseignant → ses classes, parent → ses enfants)
- [x] Isolation multi-tenant (school_id JWT, jamais du client)
- [x] Protection brute force (compte verrouillé après 5 tentatives)
- [x] Security headers (CSP, HSTS, X-Frame-Options)
- [x] Audit trail (toute action sensible tracée)
- [x] Validation Pydantic côté serveur
- [x] Requêtes SQL paramétrées (jamais de concaténation)

## 📁 Fichiers

```
YIRIBA_SAAS/
├── app/
│   ├── main.py              # Point d'entrée FastAPI
│   ├── core/
│   │   ├── config.py        # Settings via pydantic-settings
│   │   ├── database.py      # Engine async + session
│   │   ├── security.py      # JWT, bcrypt, validation
│   │   └── seeds.py         # Permissions + rôles système
│   ├── models/
│   │   ├── school.py        # School (tenant root)
│   │   ├── permission.py    # Permission, Role, RolePermission
│   │   ├── user.py          # User (status, role_type, confirmation)
│   │   ├── student.py       # Student
│   │   ├── class_.py        # Class, Subject, Enrollment
│   │   ├── grade.py         # Grade (D/1, D/2, Comp.)
│   │   ├── attendance.py    # Attendance
│   │   ├── payment.py       # Payment, FeeObligation
│   │   ├── audit.py         # AuditLog
│   │   └── school_setting.py # SchoolSetting
│   ├── routes/
│   │   └── auth.py          # Login, Register, Refresh
│   ├── services/
│   │   └── audit_service.py # Audit logging
│   └── middleware/
│       └── rbac.py          # RBAC + OwnershipFilter
├── tests/
│   ├── conftest.py          # Fixtures async
│   ├── test_auth.py         # Auth tests
│   └── test_security.py     # Multi-tenant + security tests
├── pyproject.toml           # ruff, mypy, pytest config
├── .env.example             # Variables d'environnement
├── .gitignore
└── README.md
```

## 🛠️ Développement

```bash
# Lint
ruff check .

# Format
ruff format .

# Type check
mypy app/

# Pre-commit hooks
pre-commit install
```

## 📄 Licence

Propriétaire — © 2026 Yiriba. Tous droits réservés.
