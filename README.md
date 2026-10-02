# Prints On Demand

Prints On Demand is a planned printing-service web application for students. Students will find a printing shop, submit documents with printing instructions, choose a recipient and fulfillment method, and follow an order through completion.

**Current stage: Stage 0 — specification and repository foundation only.** There is no runnable application, database schema, authentication, payment integration, or implemented UI yet. Empty directories reserve space for later work.

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

Dependency selection and installation belong to Stage 1. No dependency manifest or application code is included in this stage.

## Development stages

| Stage | Scope |
| --- | --- |
| 0 — Foundation (current) | Repository inspection, specification, configuration placeholders, and directory layout. |
| 1 — Application setup | Flask application factory, configuration validation, extensions, dependency manifest, PostgreSQL connectivity, migrations, and basic checks. |
| 2 — Accounts and administration | Authentication, role permissions, shop/staff management, professors and approvals, and configurable prices. |
| 3 — Ordering and file storage | Private uploads, print configuration, recipient validation, server-side quotations, and order submission. |
| 4 — Payment and fulfillment | Manual payment verification, onsite collection, guarded status updates, tracking, and order history. |
| 5 — UI implementation and refinement | Review the reference PDF and implement/refine student, staff, and admin flows with responsive and accessible screens. |
| 6 — Release preparation | Security and workflow testing, persistent storage, production configuration, and Render deployment. |

Stages after Stage 0 are a proposed implementation sequence and have not started.

## Repository layout

```text
app/
  routes/             Future Flask blueprints and request handlers
  models/             Future SQLAlchemy models
  services/           Future pricing, ordering, and payment rules
  storage/            Future private storage interface and adapters
  templates/          Future Jinja templates
  static/
    css/              Future stylesheets
    js/               Future vanilla JavaScript
    images/           Public UI assets only; never uploaded documents
docs/
  project-specification.md
  ui-reference.md
  references/         Reserved for the supplied UI reference PDF
tests/                Future pytest tests
```

`.gitkeep` files preserve empty directories; they contain no implementation. The application factory, configuration module, extension initialization, and entry points will be added in Stage 1. Flask-Migrate will generate `migrations/` when the database setup is implemented.

## Local development plan

For now, read the specification and UI reference notes. To prepare the environment later:

1. Install Python 3.12 and PostgreSQL and create a dedicated local development database.
2. Create a virtual environment with `python -m venv .venv`.
3. Activate it with `.venv\Scripts\Activate.ps1` on PowerShell or `source .venv/bin/activate` on macOS/Linux.
4. Copy `.env.example` to `.env` and fill in local values. On PowerShell, use `Copy-Item .env.example .env`; on macOS/Linux, use `cp .env.example .env`.
5. In Stage 1, add and install the dependency manifest, implement configuration loading, initialize migrations, and document the exact Flask and pytest commands.

The environment file currently contains names with empty values only; it is not a working configuration. Never commit `.env`, passwords, payment receipts, uploaded documents, or production data. Runtime commands will be documented once they exist. Gunicorn is intended for Render's production Linux environment.

## Deployment target and storage

Source control will use GitHub and deployment will target Render with PostgreSQL. Runtime settings and secrets will come from environment variables. Render service configuration and a Gunicorn startup command will be added when a real application entry point exists.

Local uploads are for development only and must not be assumed durable in production. The planned storage interface will support private persistent/object storage independently of the application's local filesystem. See the [storage and deployment specification](docs/project-specification.md#storage-and-deployment).

## UI/UX reference

**PrintsOnDemand Mobile.pdf** is the designated primary student UI reference. It was not present in the repository or supplied attachment directory during Stage 0, so its actual pages have not been reviewed. [UI reference notes](docs/ui-reference.md) record the supplied terminology, flow, and required extensions for later implementation.
