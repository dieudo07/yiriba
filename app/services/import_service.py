"""Yiriba SaaS — Mass Student Import Service.

4-step flow:
  1. detect_columns  — parse CSV/Excel, auto-detect column mapping
  2. validate        — check every row without writing to DB
  3. confirm         — atomic import of valid rows only
  4. cleanup         — remove stale import sessions
"""

from __future__ import annotations

import io
import json
import re
import secrets
import unicodedata
from datetime import date, datetime
from difflib import SequenceMatcher
from typing import Any

import pandas as pd
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.class_ import Class, Enrollment
from app.models.parent_student import ParentStudent
from app.models.student import Student
from app.models.user import User
from app.core.security import hash_password

# ── Column variant dictionary ──────────────────────────────────────

COLUMN_VARIANTS: dict[str, list[str]] = {
    "last_name": [
        "nom", "nom de famille", "nom_eleve", "nom eleve", "nom elève",
        "family_name", "surname", "lastname", "last name", "nom famille",
        "nom Famille", "NOM",
    ],
    "first_name": [
        "prenom", "prénom", "prenom eleve", "prenom élève",
        "prenom_eleve", "prenom eleve", "prénom eleve",
        "first_name", "firstname", "first name", "given_name",
    ],
    "birth_date": [
        "date de naissance", "date_naissance", "datenaissance", "naissance",
        "birth_date", "birthdate", "birth date", "nee_le", "née le",
        "date naissance", "datedenaissance",
    ],
    "gender": [
        "sexe", "genre", "gender", "sex", "genre_eleve", "genre eleve",
    ],
    "class_name": [
        "classe", "class", "classe_eleve", "classe eleve", "classe élève",
        "nom_classe", "nom classe",
    ],
    "parent_name": [
        "parent", "nom parent", "tuteur", "responsable", "parent_name",
        "nom du parent", "nom tuteur", "nom_tuteur", "responsable légal",
    ],
    "parent_phone": [
        "tel parent", "téléphone parent", "phone parent", "tel_parent",
        "contact parent", "telephone parent", "tel parent", "téléphone_parent",
        "tel_parent", "telephone_parent",
    ],
    "parent_email": [
        "email parent", "mail parent", "courriel parent", "parent_email",
        "email_parent", "mail_parent",
    ],
    "matricule": [
        "matricule", "numéro", "numero", "id_eleve", "reference",
        "num eleve", "numéro eleve",
    ],
}

# ── In-memory session store (replace with Redis in production) ─────

_import_sessions: dict[str, dict[str, Any]] = {}

# ── Helpers ────────────────────────────────────────────────────────


def _normalize(text: str) -> str:
    """Lowercase, strip accents, collapse spaces/underscores."""
    text = text.strip().lower()
    # Remove accents
    text = unicodedata.normalize("NFD", text)
    text = "".join(c for c in text if unicodedata.category(c) != "Mn")
    # Collapse whitespace and underscores
    text = re.sub(r"[\s_\-]+", " ", text).strip()
    return text


def _match_column(header: str, field: str) -> float:
    """Return confidence 0..1 that `header` matches `field`."""
    norm = _normalize(header)
    variants = COLUMN_VARIANTS.get(field, [])

    # Exact match (highest priority)
    for v in variants:
        if norm == _normalize(v):
            return 1.0

    # Check substring — but only if header is NOT an exact match for another field
    # This prevents 'Nom' (exact match for last_name) from matching parent_name
    has_exact_other = False
    for other_field, other_variants in COLUMN_VARIANTS.items():
        if other_field == field:
            continue
        for ov in other_variants:
            if norm == _normalize(ov):
                has_exact_other = True
                break
        if has_exact_other:
            break

    if not has_exact_other:
        # Substring match — header contains variant or vice versa
        for v in variants:
            vn = _normalize(v)
            if vn in norm or norm in vn:
                # Prefer longer variant matches (more specific)
                return 0.80

    # Fuzzy match
    best = 0.0
    for v in variants:
        ratio = SequenceMatcher(None, norm, _normalize(v)).ratio()
        if ratio > best:
            best = ratio
    return round(best, 2) if best >= 0.7 else 0.0


def _parse_date(value: str) -> date | None:
    """Try multiple date formats."""
    value = value.strip()
    if not value:
        return None
    formats = [
        "%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y", "%m/%d/%Y",
        "%d.%m.%Y", "%Y/%m/%d", "%d %m %Y",
    ]
    for fmt in formats:
        try:
            return datetime.strptime(value, fmt).date()
        except ValueError:
            continue
    # Last resort: try pandas
    try:
        return pd.to_datetime(value).date()
    except Exception:
        return None


def _parse_gender(value: str) -> str:
    """Normalize gender to M/F."""
    v = value.strip().upper()[:1]
    if v in ("M", "F"):
        return v
    v_lower = value.strip().lower()
    if v_lower in ("masculin", "homme", "male", "garçon", "garcon"):
        return "M"
    if v_lower in ("feminin", "femme", "female", "fille"):
        return "F"
    return "M"  # default


def _fuzzy_class_match(target: str, existing_classes: list[str]) -> str | None:
    """Find the closest class name. Returns None if confidence < 0.6."""
    norm_target = _normalize(target)
    best_match = None
    best_score = 0.0
    for cls_name in existing_classes:
        score = SequenceMatcher(None, norm_target, _normalize(cls_name)).ratio()
        if score > best_score:
            best_score = score
            best_match = cls_name
    return best_match if best_score >= 0.6 else None


def _read_file(file_bytes: bytes, filename: str) -> pd.DataFrame:
    """Read CSV or Excel file into a DataFrame."""
    if filename.endswith(".csv"):
        # Try UTF-8 first, then latin-1
        try:
            text = file_bytes.decode("utf-8-sig")
        except UnicodeDecodeError:
            text = file_bytes.decode("latin-1")
        return pd.read_csv(io.StringIO(text))
    elif filename.endswith((".xlsx", ".xls")):
        return pd.read_excel(io.BytesIO(file_bytes))
    else:
        raise ValueError(f"Format non supporté: {filename}")


# ── Step 1: Detect columns ─────────────────────────────────────────


async def detect_columns(
    file_bytes: bytes,
    filename: str,
) -> dict[str, Any]:
    """Parse file and auto-detect column mapping."""
    df = _read_file(file_bytes, filename)
    headers = list(df.columns.astype(str))

    mapping: dict[str, dict[str, Any]] = {}
    for field in COLUMN_VARIANTS:
        best_col = None
        best_conf = 0.0
        for header in headers:
            conf = _match_column(str(header), field)
            if conf > best_conf:
                best_conf = conf
                best_col = str(header)
        mapping[field] = {
            "column": best_col if best_conf >= 0.6 else None,
            "confidence": best_conf,
        }

    # Sample rows (first 5, as dicts)
    sample_rows = []
    for _, row in df.head(5).iterrows():
        sample_rows.append({k: str(v) if pd.notna(v) else "" for k, v in row.items()})

    return {
        "headers": headers,
        "mapping": mapping,
        "sample_rows": sample_rows,
        "total_rows": len(df),
    }


# ── Step 3: Validate ──────────────────────────────────────────────


async def validate_import(
    file_bytes: bytes,
    filename: str,
    mapping: dict[str, str],
    school_id: int,
    db: AsyncSession,
) -> dict[str, Any]:
    """Validate every row without writing. Returns errors + preview + session_id."""
    df = _read_file(file_bytes, filename)
    headers = list(df.columns.astype(str))

    # Invert mapping: field -> column name
    field_to_col: dict[str, str] = {}
    for field, col_name in mapping.items():
        if col_name and col_name in headers:
            field_to_col[field] = col_name

    # Load existing classes for this school + active academic year
    classes_result = await db.execute(
        select(Class).where(
            Class.school_id == school_id,
            Class.is_active.is_(True),  # noqa: E712
        )
    )
    existing_classes = {c.name: c.id for c in classes_result.scalars().all()}

    # Load existing students for duplicate detection
    existing_students_result = await db.execute(
        select(Student.first_name, Student.last_name, Student.birth_date).where(
            Student.school_id == school_id,
            Student.status == "active",
        )
    )
    existing_set = set()
    for row in existing_students_result:
        bd = row[2]
        if bd:
            if isinstance(bd, datetime):
                bd = bd.date()
            existing_set.add((row[0].strip().lower(), row[1].strip().lower(), bd))

    # Load max matricule for auto-generation (uniform ELV-YYYY-NNNN format)
    from datetime import datetime as _dt
    _year = _dt.now().year
    _prefix = f"ELV-{_year}-"
    max_mat_result = await db.execute(
        select(Student.matricule).where(
            Student.school_id == school_id,
            Student.matricule.like(f"{_prefix}%"),
        ).order_by(Student.matricule.desc()).limit(1)
    )
    max_mat = max_mat_result.scalar_one_or_none()
    mat_counter = 0
    if max_mat:
        try:
            mat_counter = int(max_mat.split("-")[-1])
        except (ValueError, IndexError):
            mat_counter = 0

    errors: list[dict[str, Any]] = []
    valid_rows: list[dict[str, Any]] = []
    duplicates_count = 0
    seen_in_file: set = set()  # Doublons intra-fichier
    classes_used: dict[str, int] = {}  # class_name -> class_id

    for idx, (_, row) in enumerate(df.iterrows()):
        row_num = idx + 2  # +2 because row 1 is header
        row_data: dict[str, Any] = {}
        row_errors: list[str] = []

        # Extract fields
        first_name = str(row.get(field_to_col.get("first_name", ""), "")).strip() if field_to_col.get("first_name") else ""
        last_name = str(row.get(field_to_col.get("last_name", ""), "")).strip() if field_to_col.get("last_name") else ""
        birth_date_str = str(row.get(field_to_col.get("birth_date", ""), "")).strip() if field_to_col.get("birth_date") else ""
        gender_str = str(row.get(field_to_col.get("gender", ""), "")).strip() if field_to_col.get("gender") else ""
        class_name_str = str(row.get(field_to_col.get("class_name", ""), "")).strip() if field_to_col.get("class_name") else ""
        parent_name_str = str(row.get(field_to_col.get("parent_name", ""), "")).strip() if field_to_col.get("parent_name") else ""
        parent_phone_str = str(row.get(field_to_col.get("parent_phone", ""), "")).strip() if field_to_col.get("parent_phone") else ""
        parent_email_str = str(row.get(field_to_col.get("parent_email", ""), "")).strip() if field_to_col.get("parent_email") else ""
        matricule_str = str(row.get(field_to_col.get("matricule", ""), "")).strip() if field_to_col.get("matricule") else ""

        # Clean NaN
        first_name = first_name if first_name and first_name != "nan" else ""
        last_name = last_name if last_name and last_name != "nan" else ""
        birth_date_str = birth_date_str if birth_date_str and birth_date_str != "nan" else ""
        gender_str = gender_str if gender_str and gender_str != "nan" else ""
        class_name_str = class_name_str if class_name_str and class_name_str != "nan" else ""
        parent_name_str = parent_name_str if parent_name_str and parent_name_str != "nan" else ""
        parent_phone_str = parent_phone_str if parent_phone_str and parent_phone_str != "nan" else ""
        parent_email_str = parent_email_str if parent_email_str and parent_email_str != "nan" else ""
        matricule_str = matricule_str if matricule_str and matricule_str != "nan" else ""

        # Validate required fields
        if not first_name:
            row_errors.append("Prénom manquant")
        if not last_name:
            row_errors.append("Nom manquant")

        # Parse birth_date
        birth_date = _parse_date(birth_date_str) if birth_date_str else None
        if birth_date_str and not birth_date:
            row_errors.append(f"Date de naissance invalide: '{birth_date_str}'")

        # Parse gender
        gender = _parse_gender(gender_str) if gender_str else "M"

        # Validate class
        class_id = None
        if class_name_str:
            if class_name_str in existing_classes:
                class_id = existing_classes[class_name_str]
                classes_used[class_name_str] = class_id
            else:
                closest = _fuzzy_class_match(class_name_str, list(existing_classes.keys()))
                if closest:
                    row_errors.append(
                        f"Classe '{class_name_str}' introuvable — la plus proche: '{closest}'"
                    )
                else:
                    row_errors.append(f"Classe '{class_name_str}' introuvable")
        else:
            row_errors.append("Classe manquante")

        # Check duplicate (base existante + doublons intra-fichier)
        is_duplicate = False
        if first_name and last_name and birth_date:
            key = (first_name.lower(), last_name.lower(), birth_date)
            if key in existing_set or key in seen_in_file:
                is_duplicate = True
                duplicates_count += 1
            else:
                seen_in_file.add(key)

        # Auto-generate matricule if absent — uniform ELV-YYYY-NNNN format
        if not matricule_str:
            mat_counter += 1
            matricule_str = f"{_prefix}{mat_counter:04d}"

        if row_errors:
            for err in row_errors:
                errors.append({"row": row_num, "field": "data", "message": err})
        elif is_duplicate:
            errors.append({
                "row": row_num,
                "field": "duplicate",
                "message": f"Doublon: {first_name} {last_name} existe déjà",
            })
        else:
            valid_rows.append({
                "row": row_num,
                "first_name": first_name,
                "last_name": last_name,
                "birth_date": birth_date.isoformat() if birth_date else None,
                "gender": gender,
                "class_id": class_id,
                "class_name": class_name_str,
                "matricule": matricule_str,
                "parent_name": parent_name_str,
                "parent_phone": parent_phone_str,
                "parent_email": parent_email_str,
            })

    # Create session
    session_id = secrets.token_hex(16)
    _import_sessions[session_id] = {
        "school_id": school_id,
        "valid_rows": valid_rows,
        "created_at": datetime.utcnow().isoformat(),
        "total_rows": len(df),
        "error_count": len(errors),
        "valid_count": len(valid_rows),
        "duplicates_skipped": duplicates_count,
    }

    # Preview: first 10 valid rows
    preview = valid_rows[:10]

    return {
        "valid_count": len(valid_rows),
        "error_count": len(errors),
        "duplicates_skipped": duplicates_count,
        "errors": errors[:50],  # limit to 50 errors displayed
        "preview": preview,
        "session_id": session_id,
    }


# ── Step 4: Confirm import ────────────────────────────────────────


async def confirm_import(
    session_id: str,
    school_id: int,
    db: AsyncSession,
    create_accounts: bool = False,
) -> dict[str, Any]:
    """Atomically import all valid rows from the session."""
    session = _import_sessions.get(session_id)
    if not session:
        raise ValueError("Session d'import introuvable ou expirée")

    if session["school_id"] != school_id:
        raise ValueError("Session non autorisée pour cette école")

    valid_rows = session["valid_rows"]
    imported = 0
    parents_created = 0
    parents_linked = 0
    accounts_created = 0
    import_errors: list[str] = []

    try:
        # Load classes once
        classes_result = await db.execute(
            select(Class).where(Class.school_id == school_id, Class.is_active.is_(True))  # noqa: E712
        )
        class_map = {c.name: c.id for c in classes_result.scalars().all()}

        # Load active academic year
        from app.models.academic_year import AcademicYear
        year_result = await db.execute(
            select(AcademicYear).where(
                AcademicYear.school_id == school_id,
                AcademicYear.is_active.is_(True),  # noqa: E712
            )
        )
        active_year = year_result.scalar_one_or_none()
        academic_year_id = active_year.id if active_year else None
        academic_year_name = active_year.name if active_year else "2025-2026"

        for row_data in valid_rows:
            try:
                student = Student(
                    school_id=school_id,
                    first_name=row_data["first_name"],
                    last_name=row_data["last_name"],
                    matricule=row_data.get("matricule", ""),
                    gender=row_data.get("gender", "M"),
                )
                if row_data.get("birth_date"):
                    student.birth_date = date.fromisoformat(row_data["birth_date"])

                db.add(student)
                await db.flush()  # get student.id

                # Enroll in class if class_id known
                class_id = row_data.get("class_id")
                if not class_id and row_data.get("class_name"):
                    class_id = class_map.get(row_data["class_name"])
                if class_id and academic_year_id:
                    enrollment = Enrollment(
                        school_id=school_id,
                        student_id=student.id,
                        class_id=class_id,
                        academic_year_id=academic_year_id,
                        status="active",
                    )
                    db.add(enrollment)

                # Create parent if provided
                parent_name = row_data.get("parent_name", "")
                parent_phone = row_data.get("parent_phone", "")
                parent_email = row_data.get("parent_email", "")

                if parent_name or parent_phone:
                    # Try to find existing parent by phone or name
                    parent_user = None
                    if parent_phone:
                        phone_result = await db.execute(
                            select(User).where(
                                User.school_id == school_id,
                                User.role_type == "parent",
                                User.phone == parent_phone,
                            )
                        )
                        parent_user = phone_result.scalar_one_or_none()

                    if not parent_user and parent_name:
                        name_parts = parent_name.strip().split(None, 1)
                        p_first = name_parts[0] if name_parts else ""
                        p_last = name_parts[1] if len(name_parts) > 1 else ""
                        name_result = await db.execute(
                            select(User).where(
                                User.school_id == school_id,
                                User.role_type == "parent",
                                User.first_name == p_first,
                                User.last_name == p_last,
                            )
                        )
                        parent_user = name_result.scalar_one_or_none()

                    if not parent_user:
                        # Create new parent user
                        name_parts = parent_name.strip().split(None, 1)
                        p_first = name_parts[0] if name_parts else parent_name
                        p_last = name_parts[1] if len(name_parts) > 1 else ""
                        email = parent_email or f"parent_{secrets.token_hex(4)}@yiriba.local"
                        temp_pass = secrets.token_hex(6)

                        parent_user = User(
                            school_id=school_id,
                            first_name=p_first,
                            last_name=p_last,
                            email=email,
                            phone=parent_phone or None,
                            password_hash=hash_password(temp_pass),
                            role_type="parent",
                            status="active",
                        )
                        db.add(parent_user)
                        await db.flush()
                        parents_created += 1

                    # Link parent to student
                    existing_link = await db.execute(
                        select(ParentStudent).where(
                            ParentStudent.school_id == school_id,
                            ParentStudent.parent_id == parent_user.id,
                            ParentStudent.student_id == student.id,
                        )
                    )
                    if not existing_link.scalar_one_or_none():
                        link = ParentStudent(
                            school_id=school_id,
                            parent_id=parent_user.id,
                            student_id=student.id,
                            role="OTHER",
                            is_primary=True,
                        )
                        db.add(link)
                        parents_linked += 1

                # Create student login accounts if requested
                if create_accounts and not student.user_id:
                    from app.services.student_service import generate_yiriba_id, generate_temp_password
                    yiriba_id = await generate_yiriba_id(db, school_id)
                    temp_pass = generate_temp_password()
                    account = User(
                        school_id=school_id,
                        username=yiriba_id,
                        first_name=student.first_name,
                        last_name=student.last_name,
                        password_hash=hash_password(temp_pass),
                        role_type="student",
                        status="active",
                        must_change_password=True,
                    )
                    db.add(account)
                    await db.flush()
                    student.user_id = account.id
                    accounts_created += 1

                imported += 1

            except Exception as e:
                import_errors.append(f"Ligne {row_data.get('row', '?')}: {str(e)}")

        await db.commit()

        # Cleanup session
        _import_sessions.pop(session_id, None)

        # Audit log
        from app.services.audit_service import log_action
        try:
            await log_action(
                db,
                school_id=school_id,
                user_id=None,
                action="IMPORT_ELEVES",
                resource="student",
                details={"imported": imported, "errors": len(import_errors)},
            )
        except Exception:
            pass  # Don't fail import if audit log fails

        return {
            "imported": imported,
            "duplicates_skipped": session["duplicates_skipped"],
            "parents_created": parents_created,
            "parents_linked": parents_linked,
            "accounts_created": accounts_created,
            "errors": import_errors,
        }

    except Exception as e:
        await db.rollback()
        raise ValueError(f"Erreur lors de l'import: {str(e)}")
