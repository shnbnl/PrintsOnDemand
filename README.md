# Prints On Demand

A campus printing service for students, professors, and print shops. Customers upload documents, configure printing, choose fulfillment and payment, and track their orders. Shop staff manage prices, payments, and print jobs for their assigned shop.

## Features

- Student and professor registration with role-based workspaces.
- Shop search, list/map views, operating hours, services, and prices.
- Guided checkout with up to 20 files per order and a 25 MiB individual upload ceiling. The combined upload request also has a size limit.
- Letter, Legal, A4, A3, and A2 paper; grayscale/color; copy counts; optional rush printing.
- Scheduled pickup, regular delivery where offered, and Blue and Silver professor delivery.
- Shop-specific cash and manual online payment options, payment QR images, reference submission, and staff verification.
- Order references, saved price/recipient details, tracking, filtered customer history, and customer-confirmed completion.
- Staff shop settings with service/payment switches, bulk price editing, photos, hours, and fees.
- Blue and Silver professor verification with automatically managed profiles and delivery approval controls.

## Accounts and order processing

| Role | Access |
|---|---|
| Student | Own files, checkout, eligible professor recipients, own orders and completion |
| Professor | Own files/orders and eligible delivery to their assigned Faculty |
| Shop staff | Assigned shop settings, payments, order files, and printing progress |
| Administrator | Shops, staff assignments, and authorized payment management |

Only Blue and Silver staff manage professor verification and approval. Public registration cannot create staff or administrator accounts. Professor verification creates or associates a profile using the registered identity, department, and faculty; delivery approval remains a separate staff decision.

Checkout follows **Upload → Shop → Fulfillment → Payment → Review**. Prices are calculated on the server and saved on placement. A zero paper/color rate means that combination is unavailable. Rush printing adds **PHP 20 once per order**, when offered; delivery is charged separately.

Verifying an online payment or confirming cash starts processing if the order is awaiting payment. Staff then mark the job ready and, for professor delivery, record the physical handoff. Only the customer completes an eligible paid order. Professor self-delivery can use eligible cash-on-delivery processing before collection; completion still requires recorded payment.

Payments are manually checked by authorized staff. The app does not transfer money, book couriers, operate printers, or email documents to professors.

## Requirements

- Python 3.12
- SQLite for local development/current PythonAnywhere deployment, or PostgreSQL
- Dependencies in [requirements.txt](requirements.txt)
- LibreOffice or AbiWord for Word document page counting
- Google Maps JavaScript API configuration for interactive maps
- GnuPG for encrypted backups; compatible `pg_dump` for PostgreSQL backups

Flask serves Jinja templates with JavaScript/CSS. SQLAlchemy, Flask-Migrate, Flask-Login, and Flask-WTF provide database, migration, authentication, and form support. Linux deployments may use `gunicorn wsgi:app`; PythonAnywhere uses its configured WSGI application.

## Local setup

```bash
python -m venv .venv
```

Activate the environment:

```powershell
# Windows PowerShell
.venv\Scripts\Activate.ps1
Copy-Item .env.example .env
```

```bash
# Linux / macOS
source .venv/bin/activate
cp .env.example .env
```

Set a stable signing secret and other local settings in `.env`, then run:

```bash
python -m pip install -r requirements.txt
python -m flask --app run.py db upgrade
python run.py
```

Open `http://127.0.0.1:5000`. The existing migration environment is initialized; do not run `db init` again. `/health` checks process liveness only.

To create an administrator or assigned staff account from a trusted server shell:

```bash
python -m flask --app run.py create-privileged-user --role ADMIN
python -m flask --app run.py create-privileged-user --role SHOP_STAFF --shop-id SHOP_ID
```

The commands prompt for account details and a hidden password. Create the shop before assigning staff. For optional development fixtures, run `seed-sample-shops` or `seed-sample-professors` through the Flask CLI; these are not approved business data and cannot run under the production configuration.

## API keys and environment files

Store real configuration values in the local `.env`, using the variable names in
[.env.example](.env.example). The app loads `.env` with python-dotenv and reads
`GOOGLE_MAPS_API_KEY` and `GOOGLE_MAPS_MAP_ID` from its environment. Keep real keys
out of source code, templates, and the example file. `.env`, environment variants,
and common backup filenames are ignored by Git; `.env.example` contains placeholders
and remains tracked.

Git push/pull does not transfer ignored secrets. Configure the deployed host's
own `.env` or process environment separately, then reload the web app. Never paste
real keys into commits or documentation. Ignoring a file does not remove secrets
from earlier commits; revoke/rotate a key if it was previously committed.

Google Maps uses a browser-visible key. Restrict it in Google Cloud to the app's
approved website referrers and the Maps JavaScript API. Server-side credentials
must never be passed into browser templates or scripts.

## Documents and storage

Supported uploads: PDF, DOC, DOCX, PPT, PPTX, JPG, JPEG, PNG. Private documents default to ignored `instance/uploads`, outside public static assets. Configure `UPLOAD_STORAGE_ROOT` only to another private directory. Never commit uploaded documents, databases, `.env`, keys, or real credentials.

PDF pages are counted directly. Word files require a working renderer; set `WORD_CONVERTER_PATH` for a custom installation. Verify the deployed converter with:

```bash
python -m flask --app run.py check-page-count /path/to/document.docx
```

If Word rendering is unavailable, export to PDF for accurate pricing. Images and PowerPoint files currently use copy-based billing without page/slide counting. Request schedules default to same-day eligibility and shop operating-hour slots; they do not reserve courier or shop capacity.

Unattached checkout uploads expire after 24 hours by default. Completed order documents are not automatically expired. Local storage is the only implemented adapter, and the strict production profile refuses local uploads until durable private storage is implemented.

## Updating PythonAnywhere

Back up the database and private uploads first. In the Bash console:

```bash
cd /home/Decimo/PrintsOnDemand
source .venv/bin/activate
git pull --ff-only origin main
# Run if requirements.txt changed:
python -m pip install -r requirements.txt
python -m flask --app run.py db upgrade
```

Paths are case-sensitive. After all commands succeed, use **Web → Reload**. Stop and resolve command errors before reloading. Run migrations before serving code that depends on new tables. The revocable-session update requires existing users to sign in again.

The current deployment uses SQLite. Selecting `FLASK_ENV=production` requires PostgreSQL, a strong signing secret, trusted hosts, HTTPS, debug disabled, and the production storage requirements; do not change profiles without meeting those requirements.

## Security and operations

- Salted password hashes; server-revocable login credentials with idle/absolute expiry.
- Customer ownership checks, staff shop isolation, CSRF, and guarded payment/status updates.
- Shared database rate limits on login, registration, uploads, and account deletion.
- File size/type/signature checks, private storage, integrity checks, and authorized downloads.
- HTTPS enforcement, secure cookie options, privacy headers, and browser cleanup on logout/deletion.
- PostgreSQL private-row policies for orders, items, payments, uploads, and print configurations. SQLite retains application authorization and does not support these RLS policies.
- Encrypted backup and verification commands, staged-upload cleanup, and interrupted-deletion recovery.

Host settings, restricted database roles, task scheduling, backup keys, off-site copies, and recovery drills require operator configuration. File validation is not antivirus scanning. See [Security operations](docs/security-operations.md) for deployment settings, permissions, sessions, backups, and recovery.

```bash
python -m flask --app run.py security-check
python -m flask --app run.py cleanup-security-state
python -m flask --app run.py cleanup-staged-uploads
python -m flask --app run.py backup-data
python -m flask --app run.py verify-backup /private/path/backup.tar.gz.gpg
```

Use separate operator credentials for complete PostgreSQL backups/maintenance with RLS. Run `recover-account-deletions` only while the app is offline. Additional policies: [Pricing](docs/printing-rates.md), [Account deletion](docs/account-deletion.md).

## Tests

```bash
python -m pytest -q
```

Tests cover authentication, authorization, uploads, pricing, checkout, fulfillment, payments, processing, professor management, migrations, deletion, and security controls. PostgreSQL policy tests require an explicitly configured empty disposable database; encrypted-backup integration tests require GnuPG. See the security guide for their setup. Automated tests do not replace deployed configuration checks or load/browser testing.

## Repository layout

```text
app/          Flask routes, models, services, forms, templates, and static assets
docs/         Operating instructions and business policies
migrations/   Database migration history; retain for existing deployments
tests/        Application and migration regression tests
run.py        Development and Flask CLI entry point
wsgi.py       Hosted WSGI entry point
```
