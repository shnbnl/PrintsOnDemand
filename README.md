# Prints On Demand

Prints On Demand is a planned printing-service web application for students. Students will find a printing shop, submit documents with printing instructions, choose a recipient and fulfillment method, and follow an order through completion.

**Current stage: Stage 2 — authentication and role management.** Students can register and log in; staff and admin accounts can be provisioned through the server CLI. The three role-protected pages check access only. Printing shops, professors, orders, payment, uploads, dashboards, and the full reference UI remain for later stages.

## Planned features

- Search and select printing shops; view shop information, opening hours, and configurable pricing.
- Upload documents; configure quantity, paper size, grayscale/color, and regular or rush printing.
- Choose pickup (including scheduled pickup) or delivery.
- Choose Myself or Professor as the recipient. Direct-to-Professor will use a searchable list of active, approved professors, show their details automatically, and accept an optional note. Students will never enter a receiver email manually.
- Choose online or onsite payment. Initial online payment will use configurable instructions/QR codes and optional receipt uploads, followed by staff verification. No real GCash/Maya API integration is planned initially.
- Receive separate upload and order confirmations, an order reference number, status tracking, and order history.
- Give Shop Staff and Admin their own dashboards and authorized management tools.

All features above are planned, not completed. See [the project specification](docs/project-specification.md) for rules, statuses, security, and open decisions.

## User roles

| Role | Planned responsibilities |
| --- | --- |
| Student | Register/login, create orders, upload documents, select printing options and recipient, choose payment, track own orders, and view own history. |
| Shop Staff | View assigned shop orders and private files, verify payments, update progress, and mark orders ready, delivered, or completed. |
| Admin | Manage users, shops, professors, Direct-to-Professor approvals/revocations, and pricing; monitor orders. |

## Technology stack

Python 3.12, Flask, SQLAlchemy, Flask-Migrate, Flask-Login, Flask-WTF with CSRF protection, PostgreSQL, Jinja templates, vanilla JavaScript, CSS, pytest, and Gunicorn for production.

Dependencies are listed in `requirements.txt`. Gunicorn is the production WSGI server for Linux deployment; use Flask's development server locally on Windows.

## Development stages

| Stage | Scope |
| --- | --- |
| 0 — Foundation (complete) | Repository inspection, specification, configuration placeholders, and directory layout. |
| 1 — Application setup (complete) | Flask application factory, environment configuration, extensions, dependency manifest, migration environment, landing page, health route, and basic checks. |
| 2 — Authentication and roles (current) | User model, student registration, login/logout, controlled staff/admin account creation, and role-protected placeholders. |
| 3 — Ordering and file storage | Private uploads, print configuration, recipient validation, server-side quotations, and order submission. |
| 4 — Payment and fulfillment | Manual payment verification, onsite collection, guarded status updates, tracking, and order history. |
| 5 — UI implementation and refinement | Review the reference PDF and implement/refine student, staff, and admin flows with responsive and accessible screens. |
| 6 — Release preparation | Security and workflow testing, persistent storage, production configuration, and Render deployment. |

Stages 3-6 remain a proposed implementation sequence and have not started. Shop and professor administration and configurable prices are still planned, with their later stage boundaries to be finalized.

## Repository layout

```text
app/
  __init__.py         Application factory
  config.py           Development, testing, and production configuration
  extensions.py       SQLAlchemy, migrations, login, and CSRF instances
  routes/             Public, authentication, and role-check blueprints
  models/             User identity and role model
  forms.py            CSRF-protected registration and login forms
  authorization.py    Reusable role guard
  cli.py              Controlled staff/admin provisioning
  services/           Reserved for future business rules
  storage/            Reserved for future private storage adapters
  templates/          Base, landing, error, account, and access templates
  static/
    css/              Simple foundation stylesheet
    js/               JavaScript entry point
    images/           Public UI assets only; never uploaded documents
docs/
  project-specification.md
  ui-reference.md
  references/         Supplied UI reference PDF
migrations/           Flask-Migrate/Alembic environment and user-table revision
tests/                Foundation and authentication tests
run.py                Local development server entry point
wsgi.py               Production WSGI entry point
requirements.txt      Python dependencies
pytest.ini            Test discovery configuration
```

Some `.gitkeep` files still preserve empty future directories. The `users` table is the only business table in Stage 2.

## Local development plan

1. Install Python 3.12 and create a virtual environment with `python -m venv .venv`.
2. Activate it with `.venv\Scripts\Activate.ps1` on PowerShell or `source .venv/bin/activate` on macOS/Linux.
3. Install dependencies with `python -m pip install -r requirements.txt`.
4. Optionally copy `.env.example` to `.env` and set local values. PowerShell: `Copy-Item .env.example .env`; macOS/Linux: `cp .env.example .env`. An empty or unset `FLASK_ENV` selects development, which uses a local SQLite database in ignored `instance/` and an ephemeral signing secret. No `.env` is needed for the initial landing page.
5. Run `python -m flask --app wsgi:app db upgrade` to create/update the user table, then `python -m flask --app wsgi:app check-db` to verify the connection. The migration environment is already initialized; do not run `db init` again.
6. Start the local server with `python run.py` (default `http://127.0.0.1:5000/`). Check `/` and `/health`, then `/auth/register` and `/auth/login`.
7. Run tests with `python -m pytest`.

Public registration creates **STUDENT** accounts only. Use a trusted server shell to create a **SHOP_STAFF** or **ADMIN** account: `python -m flask --app wsgi:app create-privileged-user --role SHOP_STAFF` (or `--role ADMIN`). The command prompts for name, email, and a hidden password. Do not pass a password on the command line. `/student`, `/shop`, and `/admin` are authorization placeholders, not dashboards. Logout uses a CSRF-protected POST form in the page header.

`DATABASE_URL` overrides the local SQLite default; `postgres://` URLs are normalized to `postgresql://`. `FLASK_ENV` accepts `development`, `testing`, or `production`. `TESTING=true` also selects the isolated in-memory SQLite configuration; it cannot be enabled with production. Production requires a PostgreSQL `DATABASE_URL` and `SECRET_KEY`, enables secure session cookies, and does not silently use local defaults. Other names in `.env.example` reserve settings for later upload and storage stages and are not used yet. Never commit `.env`, passwords, payment receipts, uploaded documents, or production data.

## Deployment target and storage

Source control will use GitHub and deployment will target Render with PostgreSQL. Runtime settings and secrets come from environment variables. The WSGI entry point is ready for `gunicorn wsgi:app` on Linux. Render service settings and release/migration steps will be finalized before deployment.

Local uploads are for development only and must not be assumed durable in production. The planned storage interface will support private persistent/object storage independently of the application's local filesystem. See the [storage and deployment specification](docs/project-specification.md#storage-and-deployment).

## UI/UX reference

**[PrintsOnDemand Mobile.pdf](docs/references/PrintsOnDemand%20Mobile.pdf)** is the primary student UI reference. [UI reference notes](docs/ui-reference.md) record the review of all nine pages, including terminology, flow, and required extensions for later implementation. The Stage 2 account pages are functional forms; the full student UI remains for a later stage.
