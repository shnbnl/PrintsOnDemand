# Prints On Demand

Prints On Demand is a planned printing-service web application for students. Students will find a printing shop, submit documents with printing instructions, choose a recipient and fulfillment method, and follow an order through completion.

**Current stage: Stage 11 — Student Order History.** Students can review their own previous orders, filter by order or payment status, and open the existing detail and tracking page. Payment verification and pickup/delivery scheduling remain for later stages.

## Planned features

- Search and select printing shops; view shop information, opening hours, and configurable pricing.
- Upload documents; configure quantity, paper size, grayscale/color, and regular or rush printing.
- Choose pickup (including scheduled pickup) or delivery.
- Choose Myself or Professor as the recipient. Direct-to-Professor now uses a list of active, approved professors and shows their details automatically. Search, an optional note, and the broader recipient flow remain planned. Students never enter a receiver email manually.
- Choose manual online or onsite payment. Online payment currently uses configurable instructions and a student-submitted reference awaiting verification. QR codes, receipt uploads, staff verification, and gateway APIs remain later work.
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
| 5 — Order creation and checkout review (complete) | Active-shop selection, server-calculated quote, order/item snapshots, reference-based confirmation. |
| 6 — Direct-to-Professor (complete) | Approved professor selection, server-side eligibility checks, order recipient snapshots, and confirmation. |
| 7 — Payment (complete) | Manual online reference submission, onsite selection, separate payment status, and configuration-driven instructions. |
| 8 — Order confirmation and tracking (complete) | Owner-only order detail with reference, next step, and a timeline derived from order and payment records. |
| 9 — Shop Staff order processing (complete) | Assigned-shop order list/detail, scoped private file download, payment-gated processing actions, and timestamped student tracking. |
| 10 — Admin management (complete) | Admin dashboard, staff assignment and professor pages, and public payment-instruction editing; existing shop/service/price/fee controls remain in use. |
| 11 — Student Order History (current) | Owner-only order list with status filters, newest-first pagination, and links to existing detail/tracking. |
| Later stages (planned) | Payment verification, pickup/delivery, UI refinement, persistent storage, and deployment. |

Orders begin at `PENDING_PAYMENT`. Only a payment record already marked `PAID` by a trusted process permits staff to move the order to `PROCESSING`, then `READY`, then `COMPLETED`. A separate payment record uses `PENDING` when a method is selected and `SUBMITTED` when an online reference awaits manual verification. The schema reserves `PAID` and `REJECTED` for a future authorized verification workflow; no current HTTP route can set them. Admins may manage professor approval for future orders without changing historical recipient snapshots.

## Repository layout

```text
app/
  __init__.py         Application factory
  config.py           Development, testing, and production configuration
  extensions.py       SQLAlchemy, migrations, login, and CSRF instances
  routes/             Public, authentication, shop, file, order, and admin blueprints
  models/             User, shop, pricing, file, professor, order, and payment models
  forms.py            CSRF-protected registration and login forms
  shop_forms.py       Shop, service, price, fee, and staff-assignment forms
  file_forms.py       CSRF-protected upload and print-configuration forms
  order_forms.py      CSRF-protected final order form
  payment_forms.py    CSRF-protected payment method and reference forms
  admin_forms.py      CSRF-protected professor, assignment, and public payment forms
  seed.py             Explicit demo shop, pricing, and professor data
  authorization.py    Reusable role guard
  cli.py              Controlled staff/admin provisioning
  services/           Order pricing/creation, professor selection, payment, tracking, staff processing, and admin rules
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

Stage 3 added shops, services, prices, and fees. Stage 4 added uploaded files and print configurations. Stage 5 added `orders` and `order_items`; Stage 6 added professors and optional order destinations; Stage 7 added one payment record per order. Stage 8 derives tracking from those records without adding a table. Stage 9 expands the order-status constraint and adds three nullable processing timestamps. Stage 10 adds an optional single-row table for admin-managed public payment instructions; existing environment values remain the fallback until an admin saves an override.

Stage 11 reuses existing orders and payments for student history. It adds no database table or migration.

## Local development plan

1. Install Python 3.12 and create a virtual environment with `python -m venv .venv`.
2. Activate it with `.venv\Scripts\Activate.ps1` on PowerShell or `source .venv/bin/activate` on macOS/Linux.
3. Install dependencies with `python -m pip install -r requirements.txt`.
4. Optionally copy `.env.example` to `.env` and set local values. PowerShell: `Copy-Item .env.example .env`; macOS/Linux: `cp .env.example .env`. An empty or unset `FLASK_ENV` selects development, which uses a local SQLite database in ignored `instance/` and an ephemeral signing secret. No `.env` is needed for the initial landing page.
5. Run `python -m flask --app run.py db upgrade` to apply migrations through admin payment settings, then `python -m flask --app run.py db check` to confirm there are no pending schema changes. The migration environment is already initialized; do not run `db init` again.
6. Start the local server with `python run.py` (default `http://127.0.0.1:5000/`). Check `/` and `/health`, then `/auth/register` and `/auth/login`.
7. Run tests with `python -m pytest`.

Public registration creates **STUDENT** accounts only. Use a trusted server shell to create a **SHOP_STAFF** or **ADMIN** account: `python -m flask --app wsgi:app create-privileged-user --role SHOP_STAFF` (or `--role ADMIN`). The command prompts for name, email, and a hidden password. Do not pass a password on the command line. An admin assigns Shop Staff to one shop from that shop's edit page; unassigned staff cannot access shop orders. Logout uses a CSRF-protected POST form in the page header.

After logging in, students can open `/shops` to search active shops and view `/shops/<id>` for details and a price table. Admins use `/admin` to reach management pages. `/admin/shops` retains the existing shop editor for creating/editing or activating/deactivating shops, choosing services, setting paper-size/color prices and rush/delivery fees, and assigning existing staff accounts. `/admin/staff` lists Shop Staff accounts and lets an admin assign, reassign, or unassign each from one shop. These changes take effect on the staff member's next request. No user role is changed through assignment. Assigned staff see only their shop at `/shop`. The shop's `Proceed` action becomes available once the student has a configured file.

Students can open `/files` from `/student`, then `/files/upload` to store one document at a time. The detail page confirms the filename, byte size, and upload time. It also offers an authorized download, configuration, and deletion. Configuration supports Letter, Legal, A4, A3, A2; grayscale or color; print count 1–999 by default; and rush printing. One active configuration is saved per file. Upload/configuration alone does **not** submit an order. Only the owner may list, view, configure, or delete their file; assigned staff may download it only through an order for their own shop. Once a file belongs to an order, deletion is blocked so its private bytes remain available. The same file may intentionally be used for a later reprint order.

To place an order, upload and configure a file, then use its detail page or an active shop page to open `/orders/new`. Select one configured file and one shop. You may also choose **Send to professor** and select an active, approved professor when the shop offers Direct-to-Professor. The review shows the professor's database-managed name, department, office, and email; students cannot type or override a recipient email. Review the current quote and press **Place Order**. Checkout reads the shop's `PrintPrice` for the selected paper size and color, multiplies that unit rate by the configured print count, and adds the shop's flat `RUSH_PRINTING` fee only when rush is selected, the service is enabled, and its fee is configured. Delivery, professor, pickup, and payment fees are not applied. Browser-submitted prices and totals are ignored. The server recalculates on submission; if the quote or professor details changed since review, it shows the current details and requires another confirmation.

The completed order receives a unique reference such as `POD-2026-A1B2C3D4E5F6` and can be opened at `/orders/<reference>` by its student owner. `OrderItem` stores the file name, paper/color/count/rush choices, unit price, and line total; `Order` stores the selected shop name, subtotal, rush fee, fees total, currency (`PHP`), total, and optional intended professor details. Later shop-rate, configuration, or professor-profile edits do not alter those snapshots. An owner may select or change an intended professor on an existing pending order if its shop offers the service. This only records the intended recipient; **no file or email is sent to the professor**, and the professor has not been notified. New orders begin at `PENDING_PAYMENT` and remain there until payment is independently recorded as paid and staff starts processing. Orders currently contain one file, though the data model supports multiple items.

On the order detail page, choose **Onsite payment** to record a pending payment and see the configured counter instructions. Manual **Online payment** requires an enabled flag and nonempty public instructions, account name, and destination; the option stays unavailable if any detail is missing. These values can come from `ONLINE_PAYMENT_ENABLED`, `ONLINE_PAYMENT_INSTRUCTIONS`, `ONLINE_PAYMENT_ACCOUNT_NAME`, `ONLINE_PAYMENT_DESTINATION`, and `ONSITE_PAYMENT_INSTRUCTIONS` in the environment, or an admin can save a complete public-facing override at `/admin/payment`. After choosing online payment, the page shows the order reference, server-stored total and currency, and configured transfer details. Enter a payment reference to move the payment from `PENDING` to `SUBMITTED`. This is only a claim awaiting manual verification; it does **not** prove funds were received, mark the payment `PAID`, or change the order's `PENDING_PAYMENT` status. A repeated identical submission is harmless; a different reference or method change after submission is rejected. Use fictional details for development; do not commit live account details. No receipt upload, QR code, gateway integration, or staff verification interface exists yet.

The same `/orders/<reference>` page confirms the stable order reference, shop, total, intended professor when selected, payment method/status, order status, and current next step. Its **Order tracking** section shows order creation, the recorded payment state, any actual shop-processing transitions, and the current order state. It uses stored order, payment, and processing timestamps; an unrecorded step has no timestamp. Refreshing the page creates no new order, payment, or event. Only the order owner can view it.

Students can open **Order History** from the account navigation or `/student`. `/orders` lists only the signed-in student's orders, newest first, 20 per page, with optional order-status and payment-status filters. Each row uses the stored order reference, shop-name snapshot, creation time, total, status, payment state, and destination; selecting a reference opens the existing owner-only detail page. Orders remain in history if a shop or professor later becomes inactive or pricing changes. An order with no payment is labeled “Not selected,” and `SUBMITTED` means awaiting verification, not paid.

Assigned **SHOP_STAFF** users open `/shop` and follow the shop-orders link to `/staff/orders`. The list shows only their shop's orders. Each detail page shows immutable print-price and professor snapshots, payment state, and a secure download for files attached to that order. Actions are CSRF-protected POSTs with exact permitted transitions: `PENDING_PAYMENT` → `PROCESSING` → `READY` → `COMPLETED`. The first step requires the payment record to already be `PAID`, and every later step rechecks that state. Submitted online references and pending onsite payments cannot start processing. Staff actions never change payment status, prices, ownership, or recipient. Processing timestamps are generated on the server and appear in student tracking. No current staff screen verifies payment, so ordinary new orders remain pending until a future trusted verification flow exists.

Only **ADMIN** users can open `/admin/professors` to add or edit professor names, normalized unique emails, department, office, active state, and Direct-to-Professor approval. A professor must be both active and approved to appear in new student selections. Existing orders keep their recipient snapshots after edits or deactivation. The admin pages use CSRF-protected forms and never expose payment verification or order-processing actions. The public payment form stores instructions meant to be shown to students; do not enter API keys, passwords, or gateway secrets. Editing these instructions does not change any payment record.

**Pricing limit:** Stage 3 rates are presented as per-page/print-unit rates, but Stage 4 does not establish a trusted page count inside PDF or Office files. Stage 5 uses the student's print count as the number of billed print units and does not inspect document pages. This rule needs reconciliation before real payment. Local demo rates remain sample values and are labeled as such at review. No payment verification or pickup/delivery flow is implemented.

Private local uploads default to ignored `instance/uploads`, outside `app/static`. `UPLOAD_STORAGE_ROOT` selects another private root for development/testing; if it is inside the repository, add that custom path to `.gitignore`. `UPLOAD_MAX_SIZE` sets the maximum file size in bytes (default **16 MiB**) and the request cap adds 64 KiB for multipart form overhead. `UPLOAD_MAX_QUANTITY` changes the print-count ceiling (default **999**). Supported extensions are PDF, DOC, DOCX, PPT, PPTX, JPG, JPEG, and PNG. The server checks the extension, declared MIME type, and a recognizable file signature or OOXML ZIP structure. This is a screening measure, not a malware scan or complete document parser: legacy DOC/PPT share an OLE signature, and valid-looking content can still be malicious. Uploaded bytes live outside the database under random keys; metadata and SHA-256 live in the database. The current adapter is local and **production uploads are refused** until a durable private adapter is configured. Do not use an ephemeral Render filesystem for real uploads.

For development data only, run `python -m flask --app wsgi:app seed-demo-shops` explicitly after `db upgrade`. It adds four sample shops based on the PDF names, sample services, prices for Letter/Legal/A4/A3/A2 in grayscale and color, and sample rush/delivery fees where relevant. It is idempotent by shop name, does not overwrite existing shops or prices, and refuses to run in production. The seed amounts and addresses are **demo values, not approved business rates**; seeded pages label them as demo. Admins can replace prices and fees through the UI without changing code.

For fictional professor data, run `python -m flask --app wsgi:app seed-demo-professors` explicitly after `db upgrade`. It adds two active, approved professors plus unapproved and inactive examples using `example.edu` addresses. The command is idempotent by email, leaves existing records and approvals unchanged, and refuses to run in production. These records are development/demo data only; admins can subsequently manage them at `/admin/professors`.

`DATABASE_URL` overrides the local SQLite default; `postgres://` URLs are normalized to `postgresql://`. `FLASK_ENV` accepts `development`, `testing`, or `production`. `TESTING=true` also selects the isolated in-memory SQLite configuration; it cannot be enabled with production. Production requires a PostgreSQL `DATABASE_URL` and `SECRET_KEY`, enables secure session cookies, and does not silently use local defaults. Object-storage names in `.env.example` are reserved for a later adapter and are not used yet. Never commit `.env`, passwords, payment receipts, uploaded documents, or production data.

## Deployment target and storage

Source control will use GitHub and deployment will target Render with PostgreSQL. Runtime settings and secrets come from environment variables. The WSGI entry point is ready for `gunicorn wsgi:app` on Linux. Render service settings and release/migration steps will be finalized before deployment.

Local uploads are for development only and must not be assumed durable in production. The storage interface can be replaced with private persistent/object storage without changing file routes. Cleanup of abandoned uploads and recovery after a storage/database failure remain future operational work. See the [storage and deployment specification](docs/project-specification.md#storage-and-deployment).

## UI/UX reference

**[PrintsOnDemand Mobile.pdf](docs/references/PrintsOnDemand%20Mobile.pdf)** is the primary student UI reference. [UI reference notes](docs/ui-reference.md) record the review of all nine pages. Stages 6–10 added approved-professor selection, manual payment, tracking, staff processing, and admin management. Stage 11 adds a simple order-history page. The full visual design remains for later stages.
