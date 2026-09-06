# Yiriba SaaS — Déploiement test sur Render.com (gratuit)

## 1. Ce qui est préparé

- **`Dockerfile`** existe déjà (Python 3.11 + gunicorn/uvicorn, port 5050).
- **`pyproject.toml`** : `xhtml2pdf` et `jinja2` ajoutés aux dépendances (nécessaires pour les PDF bulletins/reçus, absents du fichier).
- Le seed des permissions/forfaits et la création des tables se font automatiquement au démarrage (`app/main.py`, lifespan) → **aucune migration manuelle**.
- La base SQLite (`yiriba.db`) est créée au premier lancement.
- `.env` et `*.db` sont dans `.gitignore` → les secrets vont dans le dashboard Render, **jamais dans git**.

## 2. Pousser le code sur GitHub

```bash
cd C:/Users/Dieudo/Desktop/YIRIBA_SAAS
git add pyproject.toml DEPLOY_RENDER.md
git commit -m "chore: add xhtml2pdf/jinja2 deps + render deploy guide"
git push origin main
```

(Autres fichiers modifiés — app.js, style.css, auth.py, etc. — à committer aussi pour que le serveur ait la dernière version de l'interface.)

## 3. Créer le service sur Render

1. https://dashboard.render.com → **New** → **Web Service**
2. Connecter le repo GitHub `dieudo07/YIRIBA_SAAS`
3. Configuration :
   - **Runtime** : Docker
   - **Region** : Frankfurt (le plus proche du Burkina)
   - **Instance Type** : Free
4. **Environment variables** (bouton *Add Environment Variable*) :

| Clé | Valeur |
|---|---|
| `APP_ENV` | `production` |
| `APP_DEBUG` | `false` |
| `APP_SECRET_KEY` | (chaîne aléatoire 32+ caractères) |
| `JWT_SECRET_KEY` | (autre chaîne aléatoire 32+ caractères) |
| `SERVER_URL` | `https://<ton-nom>.onrender.com` |
| `DATABASE_URL` | `sqlite+aiosqlite:///./yiriba.db` |
| `PLATFORM_ADMIN_EMAILS` | `votre-email-support@votre-domaine.com` |
| `TURNSTILE_SITE_KEY` / `TURNSTILE_SECRET_KEY` | (copier depuis le `.env` local, ou vider pour désactiver le captcha en test) |
| `RATE_LIMIT_LOGIN` | `20/minute` |
| `RATE_LIMIT_API` | `120/minute` |

5. **Create Web Service** → le build Docker prend ~5-10 min.

## 4. Limites du plan gratuit Render

- Le service **s'endort après 15 min d'inactivité** → première requête suivante lente (~50 s de réveil).
- **512 Mo RAM** — suffisant pour un test, juste pour quelques utilisateurs.
- **Disque éphémère** : la base SQLite et les uploads sont **réinitialisés à chaque redéploiement**. C'est OK pour tester ; pour garder les données, ajouter un **Disk** (1 Go gratuit) monté sur `/app/data` et mettre `DATABASE_URL=sqlite+aiosqlite:////app/data/yiriba.db` + `UPLOAD_DIR=/app/data/uploads`.
- Render free n'accepte que du HTTPS — rien à configurer, c'est automatique.

## 5. Vérifier après déploiement

1. `https://<ton-nom>.onrender.com/health` → `{"status": "ok"}`
2. Ouvrir `https://<ton-nom>.onrender.com/` → écran de connexion YIRIBA
3. **Créer une école de test** via « Créer une école » (le captcha Turnstile doit être désactivé ou configuré pour le nouveau domaine).
4. Tester : élèves, notes, bulletin PDF, reçu PDF, notifications.

## 6. Turnstile (captcha) sur le nouveau domaine

Cloudflare Turnstile est lié à un domaine. Après déploiement :
- soit ajouter `https://<ton-nom>.onrender.com` dans les domaines autorisés du widget Turnstile sur le dashboard Cloudflare,
- soit laisser `TURNSTILE_SECRET_KEY` vide dans Render → le captcha est automatiquement désactivé (le code saute la vérification si la clé est vide).

## 7. Mettre à jour le code plus tard

Chaque `git push origin main` déclenche un redéploiement automatique.
