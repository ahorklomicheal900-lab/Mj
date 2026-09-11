# Alcantara Daily Sales Desk

Production-ready Flask daily sales dashboard with role-based accounts, sales/profit tracking, reports, team management and an owner Backstage panel.

## What was prepared

The original project stored sales, users and logs only in RAM. This version uses persistent storage:

- PostgreSQL when `DATABASE_URL` is configured (recommended for Render).
- SQLite automatically for local development when `DATABASE_URL` is absent.
- Sales, accounts, settings, login history and activity history survive restarts/redeploys when PostgreSQL is used.
- Existing routes and frontend API response shapes remain compatible.
- `/health` is included for Render health checks.

## GitHub

Upload the **contents of `shop-sales-app/`** to the root of your GitHub repository. The root should contain:

```text
app.py
requirements.txt
Procfile
render.yaml
README.md
.gitignore
.env.example
static/
templates/
```

Do not upload `.env`, database files, or real passwords.

## Render — easiest method

1. Push the project to GitHub.
2. In Render, create a Blueprint and select the repository.
3. Render will use `render.yaml` to create the web service and PostgreSQL database.
4. Set the requested `INITIAL_OWNER_PASSWORD` to a strong password.
5. Deploy.
6. Open the generated Render URL and sign in with the configured owner username/password.

## Render — manual method

**Build command**

```text
pip install -r requirements.txt
```

**Start command**

```text
gunicorn app:app --bind 0.0.0.0:$PORT --workers 2 --timeout 120
```

**Health check path**

```text
/health
```

Connect a Render PostgreSQL database and make its connection string available to the web service as `DATABASE_URL`.

Set:

| Variable | Value |
|---|---|
| `SECRET_KEY` | Long random secret |
| `DATABASE_URL` | Render PostgreSQL connection string |
| `INITIAL_OWNER_USERNAME` | Your owner username |
| `INITIAL_OWNER_PASSWORD` | Strong owner password |
| `INITIAL_OWNER_DISPLAY_NAME` | Shop owner display name |
| `SEED_DEMO_USERS` | `0` for production |

## Local development

```bash
python -m venv venv
# Windows: venv\\Scripts\\activate
# macOS/Linux: source venv/bin/activate
pip install -r requirements.txt
python app.py
```

Open `http://127.0.0.1:5000`.

Without `DATABASE_URL`, the app creates a local SQLite database. For quick local testing the default owner is `alcantara` / `backstage123`; change it before sharing the application.

## First deployment test

After deployment, open `/health`. A healthy app returns:

```json
{"status":"ok","database":"connected"}
```

Then test owner login, add a sale, refresh, log out/in, change password, add an employee, download a report and verify Backstage history.

## Important database warning

Do not point this new schema at an existing production database blindly. If you already have an important shop database, it needs a deliberate migration rather than `create_all()` being treated as a migration system.

## Security

Passwords are hashed. Production sessions use `SECRET_KEY`. User input in generated reports is escaped. Role restrictions are checked on the server. The final owner account cannot be demoted or removed. Use `SEED_DEMO_USERS=0` in production.

## Render deployment (fixed package)

This package is intentionally structured with `app.py`, `templates/`, and `static/` at the repository root. In Render, use the repository root as the service Root Directory (leave it blank unless your repository contains this project inside a subfolder).

Recommended settings:
- Build Command: `pip install -r requirements.txt`
- Start Command: `gunicorn app:app --bind 0.0.0.0:$PORT --workers 2 --timeout 120`
- Health Check Path: `/health`

The application explicitly resolves the `templates` and `static` directories relative to `app.py`, preventing the `TemplateNotFound: login.html` error caused by a mismatched working directory or missing template folder.

### If Render still shows `TemplateNotFound: login.html`
1. Confirm `templates/login.html` exists in the GitHub repository.
2. Confirm `app.py` is in the same repository root as the `templates` folder.
3. If using a Render Root Directory, set it to the folder containing `app.py` and `templates/`.
4. Trigger a **Manual Deploy → Clear build cache & deploy** so Render doesn't reuse an old checkout.
