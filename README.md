# Prints On Demand

Prints On Demand is a planned printing-service web application for students. Students will find a printing shop, submit documents with printing instructions, choose a recipient and fulfillment method, and follow an order through completion.

**Current stage: Stage 3 — printing shops and configurable pricing.** Students can search active shops and view services, hours, and prices. Admins can manage shops, services, prices, fees, and staff assignments. Shop Staff can view their assigned shop. Professors, orders, payment, uploads, order tracking, dashboards, and the full reference UI remain for later stages.

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
| 2 — Authentication and roles (complete) | User model, student registration, login/logout, controlled staff/admin account creation, and role-protected placeholders. |
| 3 — Shops and pricing (current) | Active-shop directory/search/details, admin shop/service/price/fee settings, staff assignment, and opt-in demo seed. |
| 4 — Ordering and file storage (planned) | Private uploads, print configuration, recipient validation, server-side quotations, and order submission. |
| 5 — Payment and fulfillment (planned) | Manual payment verification, onsite collection, guarded status updates, tracking, and order history. |
| 6 — UI and release preparation (planned) | Refine the reference UI, test workflows/security, configure persistent storage, and prepare Render deployment. |

Stages 4-6 remain a proposed sequence and have not started. Professor administration and approval are still planned; their stage boundary will be finalized with the related ordering work.

## Repository layout

```text
app/
  __init__.py         Application factory
  config.py           Development, testing, and production configuration
  extensions.py       SQLAlchemy, migrations, login, and CSRF instances
  routes/             Public, authentication, role-check, shop, and admin blueprints
  models/             User, shop, service, price, and fee models
  forms.py            CSRF-protected registration and login forms
  shop_forms.py       Shop, service, price, fee, and staff-assignment forms
  seed.py             Explicit demo shop and pricing data
  authorization.py    Reusable role guard
  cli.py              Controlled staff/admin provisioning
  services/           Reserved for future business rules
  storage/            Reserved for future private storage adapters
  templates/          Base, account, access, shop directory, and admin templates
  static/
    css/              Simple foundation stylesheet
    js/               JavaScript entry point
    images/           Public UI assets only; never uploaded documents
docs/
  project-specification.md
  ui-reference.md
  references/         Supplied UI reference PDF
migrations/           Flask-Migrate/Alembic environment and schema revisions
tests/                Foundation, authentication, shop, and pricing tests
run.py                Local development server entry point
wsgi.py               Production WSGI entry point
requirements.txt      Python dependencies
pytest.ini            Test discovery configuration
```

Some `.gitkeep` files still preserve empty future directories. Stage 3 adds `printing_shops`, `shop_services`, `print_prices`, and `shop_fees`, plus an optional staff-to-shop foreign key on `users`.

## Local development plan

1. Install Python 3.12 and create a virtual environment with `python -m venv .venv`.
2. Activate it with `.venv\Scripts\Activate.ps1` on PowerShell or `source .venv/bin/activate` on macOS/Linux.
3. Install dependencies with `python -m pip install -r requirements.txt`.
4. Optionally copy `.env.example` to `.env` and set local values. PowerShell: `Copy-Item .env.example .env`; macOS/Linux: `cp .env.example .env`. An empty or unset `FLASK_ENV` selects development, which uses a local SQLite database in ignored `instance/` and an ephemeral signing secret. No `.env` is needed for the initial landing page.
5. Run `python -m flask --app wsgi:app db upgrade` to apply the user, shop, and pricing migrations, then `python -m flask --app wsgi:app db check` to confirm there are no pending schema changes. The migration environment is already initialized; do not run `db init` again.
6. Start the local server with `python run.py` (default `http://127.0.0.1:5000/`). Check `/` and `/health`, then `/auth/register` and `/auth/login`.
7. Run tests with `python -m pytest`.

Public registration creates **STUDENT** accounts only. Use a trusted server shell to create a **SHOP_STAFF** or **ADMIN** account: `python -m flask --app wsgi:app create-privileged-user --role SHOP_STAFF` (or `--role ADMIN`). The command prompts for name, email, and a hidden password. Do not pass a password on the command line. An admin assigns Shop Staff to a shop from that shop's edit page; an unassigned staff account only sees the access placeholder. Logout uses a CSRF-protected POST form in the page header.

After logging in, students can open `/shops` to search active shops and view `/shops/<id>` for details and a per-page price table. Admins use `/admin/shops` to create and edit shops, activate/deactivate them, choose services, set paper-size/color prices and rush/delivery fees, and assign existing staff accounts. Assigned staff see only their shop at `/shop`. The `Proceed` button on shop details is intentionally disabled until ordering exists.

For development data only, run `python -m flask --app wsgi:app seed-demo-shops` explicitly after `db upgrade`. It adds four sample shops based on the PDF names, sample services, prices for Letter/Legal/A4/A3/A2 in grayscale and color, and sample rush/delivery fees where relevant. It is idempotent by shop name, does not overwrite existing shops or prices, and refuses to run in production. The seed amounts and addresses are **demo values, not approved business rates**; seeded pages label them as demo. Admins can replace prices and fees through the UI without changing code.

`DATABASE_URL` overrides the local SQLite default; `postgres://` URLs are normalized to `postgresql://`. `FLASK_ENV` accepts `development`, `testing`, or `production`. `TESTING=true` also selects the isolated in-memory SQLite configuration; it cannot be enabled with production. Production requires a PostgreSQL `DATABASE_URL` and `SECRET_KEY`, enables secure session cookies, and does not silently use local defaults. Other names in `.env.example` reserve settings for later upload and storage stages and are not used yet. Never commit `.env`, passwords, payment receipts, uploaded documents, or production data.

## Deployment target and storage

Source control will use GitHub and deployment will target Render with PostgreSQL. Runtime settings and secrets come from environment variables. The WSGI entry point is ready for `gunicorn wsgi:app` on Linux. Render service settings and release/migration steps will be finalized before deployment.

Local uploads are for development only and must not be assumed durable in production. The planned storage interface will support private persistent/object storage independently of the application's local filesystem. See the [storage and deployment specification](docs/project-specification.md#storage-and-deployment).

## UI/UX reference

**[PrintsOnDemand Mobile.pdf](docs/references/PrintsOnDemand%20Mobile.pdf)** is the primary student UI reference. [UI reference notes](docs/ui-reference.md) record the review of all nine pages, including terminology, flow, and required extensions for later implementation. Stage 3 implements the shop search, detail, services, and pricelist concepts as functional pages; map layout and full visual polish remain for a later UI stage.
