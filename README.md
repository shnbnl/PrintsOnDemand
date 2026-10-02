# Prints On Demand

Prints On Demand is a planned printing-service web application for students. Students will find a printing shop, submit documents with printing instructions, choose a recipient and fulfillment method, and follow an order through completion.

**Current stage: Stage 5 — student order creation and checkout review.** Students can search shops, privately upload and configure files, review a database-priced quote, place an order, and open its reference-based confirmation. Admins manage shop services and prices; Shop Staff can view their assigned shop. Payment, professors, pickup/delivery scheduling, tracking, and staff order processing remain for later stages.

## Planned features

- Search and select printing shops; view shop information, opening hours, and configurable pricing.
- Upload documents; configure quantity, paper size, grayscale/color, and regular or rush printing.
- Choose pickup (including scheduled pickup) or delivery.
- Choose Myself or Professor as the recipient. Direct-to-Professor will use a searchable list of active, approved professors, show their details automatically, and accept an optional note. Students will never enter a receiver email manually.
- Choose online or onsite payment. Initial online payment will use configurable instructions/QR codes and optional receipt uploads, followed by staff verification. No real GCash/Maya API integration is planned initially.
- Receive separate upload and order confirmations, an order reference number, status tracking, and order history.
- Give Shop Staff and Admin their own dashboards and authorized management tools.

The list combines implemented foundations with later goals. See [the project specification](docs/project-specification.md) for rules, statuses, security, and open decisions.

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
| 3 — Shops and pricing (complete) | Active-shop directory/search/details, admin shop/service/price/fee settings, staff assignment, and opt-in demo seed. |
| 4 — File upload and print configuration (complete) | Private student uploads and one active print configuration per file. |
| 5 — Order creation and checkout review (current) | Active-shop selection, server-calculated quote, order/item snapshots, reference-based confirmation. |
| Later stages (planned) | Payment, recipients, pickup/delivery, staff processing, tracking, history, UI refinement, persistent storage, and deployment. |

Stage 5 intentionally stops after order creation. The `PENDING_PAYMENT` status means the order exists and payment has **not** been completed. No payment records or methods exist yet. Professor administration and approval are still planned.

## Repository layout

```text
app/
  __init__.py         Application factory
  config.py           Development, testing, and production configuration
  extensions.py       SQLAlchemy, migrations, login, and CSRF instances
  routes/             Public, authentication, shop, file, order, and admin blueprints
  models/             User, shop, pricing, uploaded-file, print-configuration, and order models
  forms.py            CSRF-protected registration and login forms
  shop_forms.py       Shop, service, price, fee, and staff-assignment forms
  file_forms.py       CSRF-protected upload and print-configuration forms
  order_forms.py      CSRF-protected final order form
  seed.py             Explicit demo shop and pricing data
  authorization.py    Reusable role guard
  cli.py              Controlled staff/admin provisioning
  services/           Server-side order pricing and atomic order creation
  storage/            Private local adapter and reusable upload validation
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
tests/                Foundation, authentication, shop, file, and order tests
run.py                Local development server entry point
wsgi.py               Production WSGI entry point
requirements.txt      Python dependencies
pytest.ini            Test discovery configuration
```

Stage 3 added shops, services, prices, and fees. Stage 4 added uploaded files and print configurations. Stage 5 adds `orders` and `order_items`.

## Local development plan

1. Install Python 3.12 and create a virtual environment with `python -m venv .venv`.
2. Activate it with `.venv\Scripts\Activate.ps1` on PowerShell or `source .venv/bin/activate` on macOS/Linux.
3. Install dependencies with `python -m pip install -r requirements.txt`.
4. Optionally copy `.env.example` to `.env` and set local values. PowerShell: `Copy-Item .env.example .env`; macOS/Linux: `cp .env.example .env`. An empty or unset `FLASK_ENV` selects development, which uses a local SQLite database in ignored `instance/` and an ephemeral signing secret. No `.env` is needed for the initial landing page.
5. Run `python -m flask --app wsgi:app db upgrade` to apply the user, shop, file, and order migrations, then `python -m flask --app wsgi:app db check` to confirm there are no pending schema changes. The migration environment is already initialized; do not run `db init` again.
6. Start the local server with `python run.py` (default `http://127.0.0.1:5000/`). Check `/` and `/health`, then `/auth/register` and `/auth/login`.
7. Run tests with `python -m pytest`.

Public registration creates **STUDENT** accounts only. Use a trusted server shell to create a **SHOP_STAFF** or **ADMIN** account: `python -m flask --app wsgi:app create-privileged-user --role SHOP_STAFF` (or `--role ADMIN`). The command prompts for name, email, and a hidden password. Do not pass a password on the command line. An admin assigns Shop Staff to a shop from that shop's edit page; an unassigned staff account only sees the access placeholder. Logout uses a CSRF-protected POST form in the page header.

After logging in, students can open `/shops` to search active shops and view `/shops/<id>` for details and a price table. Admins use `/admin/shops` to create and edit shops, activate/deactivate them, choose services, set paper-size/color prices and rush/delivery fees, and assign existing staff accounts. Assigned staff see only their shop at `/shop`. The shop's `Proceed` action becomes available once the student has a configured file.

Students can open `/files` from `/student`, then `/files/upload` to store one document at a time. The detail page confirms the filename, byte size, and upload time. It also offers an authorized download, configuration, and deletion. Configuration supports Letter, Legal, A4, A3, A2; grayscale or color; print count 1–999 by default; and rush printing. One active configuration is saved per file. Upload/configuration alone does **not** submit an order. Only the owner may list, view, download, configure, or delete their file; staff/admin file access is not available yet. Once a file belongs to an order, deletion is blocked so its private bytes remain available. The same file may intentionally be used for a later reprint order.

To place an order, upload and configure a file, then use its detail page or an active shop page to open `/orders/new`. Select one configured file and one shop, review the current quote, and press **Place Order**. Checkout reads the shop's `PrintPrice` for the selected paper size and color, multiplies that unit rate by the configured print count, and adds the shop's flat `RUSH_PRINTING` fee only when rush is selected, the service is enabled, and its fee is configured. Delivery, professor, pickup, and payment fees are not applied. Browser-submitted prices and totals are ignored. The server recalculates on submission; if the quote changed since review, it shows the new amount and requires another confirmation.

The completed order receives a unique reference such as `POD-2026-A1B2C3D4E5F6` and can be opened at `/orders/<reference>` by its student owner. `OrderItem` stores the file name, paper/color/count/rush choices, unit price, and line total; `Order` stores the selected shop name, subtotal, rush fee, fees total, currency (`PHP`), and total. Later shop-rate or configuration edits do not alter that snapshot. Only `PENDING_PAYMENT` is used in Stage 5; the detail page explicitly says payment has not been completed. Orders currently contain one file, though the data model supports multiple items.

**Pricing limit:** Stage 3 rates are presented as per-page/print-unit rates, but Stage 4 does not establish a trusted page count inside PDF or Office files. Stage 5 uses the student's print count as the number of billed print units and does not inspect document pages. This rule needs reconciliation before real payment. Local demo rates remain sample values and are labeled as such at review. No payment collection, fulfillment choice, order history, or tracking is implemented.

Private local uploads default to ignored `instance/uploads`, outside `app/static`. `UPLOAD_STORAGE_ROOT` selects another private root for development/testing; if it is inside the repository, add that custom path to `.gitignore`. `UPLOAD_MAX_SIZE` sets the maximum file size in bytes (default **16 MiB**) and the request cap adds 64 KiB for multipart form overhead. `UPLOAD_MAX_QUANTITY` changes the print-count ceiling (default **999**). Supported extensions are PDF, DOC, DOCX, PPT, PPTX, JPG, JPEG, and PNG. The server checks the extension, declared MIME type, and a recognizable file signature or OOXML ZIP structure. This is a screening measure, not a malware scan or complete document parser: legacy DOC/PPT share an OLE signature, and valid-looking content can still be malicious. Uploaded bytes live outside the database under random keys; metadata and SHA-256 live in the database. The current adapter is local and **production uploads are refused** until a durable private adapter is configured. Do not use an ephemeral Render filesystem for real uploads.

For development data only, run `python -m flask --app wsgi:app seed-demo-shops` explicitly after `db upgrade`. It adds four sample shops based on the PDF names, sample services, prices for Letter/Legal/A4/A3/A2 in grayscale and color, and sample rush/delivery fees where relevant. It is idempotent by shop name, does not overwrite existing shops or prices, and refuses to run in production. The seed amounts and addresses are **demo values, not approved business rates**; seeded pages label them as demo. Admins can replace prices and fees through the UI without changing code.

`DATABASE_URL` overrides the local SQLite default; `postgres://` URLs are normalized to `postgresql://`. `FLASK_ENV` accepts `development`, `testing`, or `production`. `TESTING=true` also selects the isolated in-memory SQLite configuration; it cannot be enabled with production. Production requires a PostgreSQL `DATABASE_URL` and `SECRET_KEY`, enables secure session cookies, and does not silently use local defaults. Object-storage names in `.env.example` are reserved for a later adapter and are not used yet. Never commit `.env`, passwords, payment receipts, uploaded documents, or production data.

## Deployment target and storage

Source control will use GitHub and deployment will target Render with PostgreSQL. Runtime settings and secrets come from environment variables. The WSGI entry point is ready for `gunicorn wsgi:app` on Linux. Render service settings and release/migration steps will be finalized before deployment.

Local uploads are for development only and must not be assumed durable in production. The storage interface can be replaced with private persistent/object storage without changing file routes. Cleanup of abandoned uploads and recovery after a storage/database failure remain future operational work. See the [storage and deployment specification](docs/project-specification.md#storage-and-deployment).

## UI/UX reference

**[PrintsOnDemand Mobile.pdf](docs/references/PrintsOnDemand%20Mobile.pdf)** is the primary student UI reference. [UI reference notes](docs/ui-reference.md) record the review of all nine pages, including terminology, flow, and required extensions for later implementation. Stage 5 adds a basic order review and reference-based confirmation after the existing file/shop flow. Payment and the full visual design remain for later stages.
