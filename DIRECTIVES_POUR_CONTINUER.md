# DIRECTIVES — YIRIBA SaaS

Ce qui a été fait (autonome, tests verts : **166 passed**) et ce qui **doit être fait à la main**.

---

## ✅ DÉJÀ FAIT (vérifié par tests)

1. **QR bulletins signés HMAC** (anti-fraude) :
   - nouveau service `app/services/verification_service.py` (signature + vérification).
   - endpoints publics de vérification **qui n'existaient pas** (les anciens QR pointaient vers des routes 404) :
     - `GET /api/verify/bulletin/{student_id}/{class_id}/{period}/{year}[/{signature}]`
     - `GET /api/verify/receipt/{payment_id}/{token}`
   - le QR encode maintenant l'URL de vérification (plus une chaîne `YIRIBA|...` inexploitable) ; un document altéré est détecté.
   - reçus : l'URL inclut `payment_id` (le token seul ne permettait pas de retrouver le paiement).
2. **Doublon `GET /school-profile` supprimé** (admin.py : les 2 handlers étaient identiques).
3. **Code mort nettoyé** : `init_db()` (jamais appelé), `app/utils/` (vide), `app/schemas/common.py` (jamais importé), placeholders dans `compute_class_results` (`type("C", ...)`, boucles et comprehensions vides).
4. **Tests durcis** : les anciens tests utilisaient des routes inexistantes (`/api/classes/{id}/enroll`, `.../bulk`) qui échouaient silencieusement → remplacées par les vraies (`POST /api/enrollments`, `PATCH /api/grades/entry?evaluation_id=X`) avec asserts.
5. **Export ZIP** de tous les bulletins d'une classe/période : `GET /api/report-cards/class/{class_id}/export?period=T1&academic_year=2025-2026` (staff uniquement).
6. Test « aucun recalcul quand le snapshot est complet » (monkeypatch → `compute_class_results` n'est jamais appelé).

---

## 🔐 1. RÉGÉNÉRER LES SECRETS — AVANT TOUTE MISE EN LIGNE

Ils ont été **exposés dans le chat**. Regénérer **puis ne plus jamais les coller dans un chat**.

| Variable | Action |
|---|---|
| `APP_SECRET_KEY` | `python -c "import secrets; print(secrets.token_hex(32))"` |
| `JWT_SECRET_KEY` | idem |
| `RESEND_API_KEY` | nouveau token depuis resend.com/keys |
| `TURNSTILE_SECRET_KEY` | nouveau secret depuis Cloudflare /turnstile |
| `GOOGLE_CLIENT_ID` / `SECRET` | à recréer si jamais exposés (pas vus ici) |
| `CINETPAY_*` | n'existent pas encore — voir §4 |

⚠️ `APP_SECRET_KEY` sert aux signatures HMAC des QR : si vous le changez **après** avoir imprimé des bulletins, leurs QR deviendront « non authentiques ». Changez-le **avant** toute production de documents.

---

## 🌐 2. DOMAINE + HTTPS (bloqué : non acheté)

- Acheter `yiriba.app` (ou autre) ; `.app` impose HTTPS (check HSTS).
- DNS : pointeur A/AAAA vers l'hébergeur, puis activation TLS (certificat Let's Encrypt / Cloudflare).
- `SERVER_URL` **n'est pas dans `.env`** → la valeur par défaut est `http://127.0.0.1:5050`. **Sans `SERVER_URL=https://votre-domaine`, les QR scannés pointent vers localhost.** Ajouter :
  ```
  SERVER_URL=https://yiriba.app
  CORS_ORIGINS=https://yiriba.app
  ```

---

## 📧 3. RESEND (lié à dieudonnetassembedo05@gmail.com)

1. Vérifier le domaine `yiriba.app` dans Resend (SPF/DKIM/DMARC) → rendu impossible tant que le domaine n'est pas acheté.
2. Dès que possible, passer `RESEND_FROM` à une adresse du domaine vérifié (actuellement `onboarding@resend.dev` ne peut envoyer qu'à cette adresse gmail).
3. **Désactiver le click-tracking** dans le dashboard Resend : les liens de suivi (`awstrack.me`) sont bloqués par les bloqueurs de pub (uBO) → emails de confirmation/réinitialisation cassés chez certains parents.
4. En production : `REQUIRE_EMAIL_CONFIRMATION=True`. Attention : l'implémentation actuelle ne confirme qu'une partie des inscriptions (admin vs école) — vérifier la cohérence avant d'activer.

---

## 💳 4. CINETPAY (bloqué : compte en attente de validation)

- Valider le **compte marchand** CinetPay (délai côté CinetPay, rien à faire ici).
- Une fois les clés obtenues, les ajouter : `CINETPAY_SITE_ID`, `CINETPAY_API_KEY`, `CINETPAY_SECRET_KEY`.
- Le modèle `Payment` a déjà `idempotency_key` + `webhook_received` + `webhook_raw` : le webhook CinetPay peut être branché dessus sans migration.

---

## 🗄️ 5. BASE DE DONNÉES

1. **Versionner le projet** (il n'est PAS un dépôt git !) : `git init`, commit initial, `git remote add origin ...`.
2. **Alembic** : la création des tables se fait par `create_all` (mode dev uniquement) et ignore les migrations. Mettre en place Alembic avant toute évolution de schéma en production (plusieurs colonnes ont été ajoutées : `bulletins.data_json`, `payments.receipt_qr_token`, …).
3. **Régénérer les bulletins existants** de la base dev pour que leur snapshot soit enrichi (le fallback répond, mais un snapshot complet est figé et rapide). Depuis `YIRIBA_SAAS` :
   ```powershell
   .\.venv\Scripts\python.exe -X utf8 -m app.scripts.regen  # à créer, ou demander à Copilot/opencode de le faire
   ```
   *(Disponible : je peux écrire ce script et le lancer pour vous.)*
4. **`datetime.utcnow()`** est déprécié (Python 3.14) : remplacer par `datetime.now(timezone.utc)` (grep `utcnow` dans `app/`).
5. Production : passer de SQLite à **PostgreSQL** (`DATABASE_URL=postgresql+asyncpg://...`).

---

## 🧹 6. NETTOYAGE MAINTENANCE (facultatif, sans urgence)

- **Fusion v1/v2 bulletins** : deux routeurs cohabitent (`/api/bulletins` legacy et `/api/report-cards` v2) — décider si le legacy doit rester.
- **`app/routes/teacher_portal.py`** : la saisie de notes y duplique la logique de `grades.py` — consolider.
- **Ruff** : ~60 violations résiduelles majoritairement des patterns du projet (`B008` Depends dans les defaults, `E501`, `DTZ`). Deux options : configurer `pyproject.toml` avec `ignore = ["B008", ...]` (rapide, cohérent) ou corriger (long). `app/routes/verify.py` et `verification_service.py` sont déjà propres.
- `generate_sample_pdfs.py` à la racine : conserve uniquement si utile, sinon supprimer.