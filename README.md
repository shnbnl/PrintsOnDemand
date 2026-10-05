# Prints On Demand

Prints On Demand is a printing-service web application for students and professors. They can find a printing shop, submit documents with printing instructions, choose a recipient and fulfillment method, and follow an order through completion.

**Current stage: shop self-management.** Assigned shop staff can edit their shop details, services, prices, fees, and photo. The four seeded sample shops retain their verified map coordinates; reseeding updates coordinates only on matching sample records.

## Planned features

- Search and select printing shops; view shop information, opening hours, and configurable pricing.
- Upload documents; configure quantity, paper size, grayscale/color, and regular or rush printing.
- Choose Professor Delivery, Scheduled Pickup, or Delivery for a new order. Professor Delivery is available only at Blue and Silver Bookstore. Students choose an active, approved professor who accepts student print deliveries; professors can order delivery to themselves without a dropdown.
- Choose manual online or onsite payment. Online payment uses configurable instructions, an optional public QR image, and a student-submitted reference. Authorized reviewers can manually verify or reject submitted online references; receipt uploads and gateway APIs remain later work.
- Receive separate upload and order confirmations, an order reference number, status tracking, and order history.
- Give Shop Staff and Admin their own dashboards and authorized management tools.

The list combines implemented foundations with later goals. See [the project specification](docs/project-specification.md) for rules, statuses, security, and open decisions.

## User roles

| Role | Planned responsibilities |
| --- | --- |
| Student | Register/login, create orders, upload documents, select printing options and recipient, choose payment, track own orders, and view own history. |
| Professor | Register with a department, await Blue and Silver verification and profile linking, then order prints for physical delivery to themselves and manage student delivery acceptance. |
| Shop Staff | View assigned shop orders and private files, verify payments, update progress, and mark orders ready, delivered, or completed. |
| Admin | Manage users, shops, and pricing; monitor orders. Blue and Silver staff alone verify and manage professors. |

## Technology stack

Python 3.12, Flask, SQLAlchemy, Flask-Migrate, Flask-Login, Flask-WTF with CSRF protection, PostgreSQL, Jinja templates, vanilla JavaScript, CSS, pytest, and Gunicorn for production.

Dependencies are listed in `requirements.txt`. Gunicorn is the production WSGI server for Linux deployment; use Flask's development server locally on Windows.

## Development stages

| Stage | Scope |
| --- | --- |
| 0 — Foundation (complete) | Repository inspection, specification, configuration placeholders, and directory layout. |
| 1 — Application setup (complete) | Flask application factory, environment configuration, extensions, dependency manifest, migration environment, landing page, health route, and basic checks. |
| 2 — Authentication and roles (complete) | User model, student registration, login/logout, controlled staff/admin account creation, and role-protected placeholders. |
| 3 — Shops and pricing (complete) | Active-shop directory/search/details, admin shop/service/price/fee settings, staff assignment, and opt-in sample data. |
| 4 — File upload and print configuration (complete) | Private student uploads and one active print configuration per file. |
| 5 — Order creation and checkout review (complete) | Active-shop selection, server-calculated quote, order/item snapshots, reference-based confirmation. |
| 6 — Direct-to-Professor (complete) | Approved professor selection, server-side eligibility checks, order recipient snapshots, and confirmation. |
| 7 — Payment (complete) | Manual online reference submission, onsite selection, separate payment status, and configuration-driven instructions. |
| 8 — Order confirmation and tracking (complete) | Owner-only order detail with reference, next step, and a timeline derived from order and payment records. |
| 9 — Shop Staff order processing (complete) | Assigned-shop order list/detail, scoped private file download, payment-gated processing actions, and timestamped student tracking. |
| 10 — Admin management (complete) | Admin dashboard, staff assignment, and public payment-instruction editing; existing shop/service/price/fee controls remain in use. |
| 11 — Student Order History (complete) | Owner-only order list with status filters, newest-first pagination, and links to existing detail/tracking. |
| 12 — UI/UX implementation (complete) | PDF-inspired mobile-first styling and navigation across student, staff, and admin pages. |
| 13 — Security & Quality Review (complete) | Security and correctness audit, focused fixes, regression tests, and verification. |
| 14 — Google Maps shop discovery (complete) | Student map of active shops with confirmed coordinates, search, optional one-time location sharing, and a path into the existing shop/order flow. |
| 15 — Multiple Files per Order (complete) | Up to 20 distinct library files per order, individual checkout print settings, itemized quotes, and one atomic order with historical item snapshots. |
| 16 — Scheduled Pickup and Delivery (complete) | Required fulfillment choice, server-validated requested schedules, delivery contact/address, delivery fee snapshot, and updated confirmation, history, tracking, and staff detail. |
| 17 — Student payment experience (complete) | Itemized payment summary, optional configured QR image, normalized reference submission, and clearer pending/submitted status copy. |
| 18 — Payment verification (complete) | Admin and assigned-shop staff queue, manual verify/reject actions, rejection reason, and review audit fields. |
| 20 — Professor Delivery (complete) | Blue and Silver-only physical handoff, student consent and professor self-delivery, linked professor accounts, recipient snapshots, and staff instructions. |
| 21 — Finalized account and professor workflow (complete) | Public Student/Professor registration, staff-provisioned shop accounts, Blue and Silver professor management, controlled Faculty snapshots, online-only professor payment, and staff-confirmed physical handoff. |
| 26 — Professor verification (complete) | Pending/Verified/Rejected account state, Blue and Silver-only verification and profile management, linked-account eligibility, and safe migration of previously approved links. |
| Later stages (planned) | Durable private storage and deployment. |

Orders begin at `PENDING_PAYMENT`. Only a payment record marked `PAID` permits staff to move the order to `PROCESSING`, then `READY`, then `COMPLETED`. A separate payment record uses `PENDING` when a method is selected and `SUBMITTED` when an online reference awaits manual verification. An admin or assigned-shop staff member can review `SUBMITTED` online payments and record `PAID` or `REJECTED`; neither action starts processing. Students cannot perform these actions. Blue and Silver staff manage professor approval for future orders without changing historical recipient snapshots.

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
  seed.py             Explicit sample shop, pricing, and professor data
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

Stage 16 adds nullable pickup/delivery snapshot columns and a zero-defaulted delivery fee to `orders`. Existing orders, including those without a destination, retain their stored totals, items, professor details, and payment states. The migration supports upgrade and downgrade without resetting historical orders. Stage 18 adds nullable payment submission/review timestamps, reviewer ID, and rejection reason. Existing submitted payments receive a best-available submission timestamp from their prior `updated_at` value; older paid/rejected records have no invented reviewer audit. Stage 19.1 expands shop coordinate storage from six to fifteen decimal places so the supplied map coordinates are preserved.

Stage 26 adds `users.professor_verification_status` with `PENDING`, `VERIFIED`, and `REJECTED`. The migration marks an existing Professor account verified only when it is already linked to an active, approved managed profile. Other existing Professor accounts remain pending; historical order snapshots are untouched. Run `python -m flask --app run.py db upgrade` before serving the updated app. The downgrade removes only the new status column.

## Local development plan

1. Install Python 3.12 and create a virtual environment with `python -m venv .venv`.
2. Activate it with `.venv\Scripts\Activate.ps1` on PowerShell or `source .venv/bin/activate` on macOS/Linux.
3. Install dependencies with `python -m pip install -r requirements.txt`.
4. Optionally copy `.env.example` to `.env` and set local values. PowerShell: `Copy-Item .env.example .env`; macOS/Linux: `cp .env.example .env`. An empty or unset `FLASK_ENV` selects development, which uses a local SQLite database in ignored `instance/` and an ephemeral signing secret. No `.env` is needed for the initial landing page.
5. Run `python -m flask --app run.py db upgrade` to apply migrations through Stage 16 fulfillment snapshots, then `python -m flask --app run.py db check` to confirm there are no pending schema changes. The migration environment is already initialized; do not run `db init` again.
6. Start the local server with `python run.py` (default `http://127.0.0.1:5000/`). Check `/` and `/health`, then `/auth/register` and `/auth/login`.
7. Run tests with `python -m pytest`.

Public registration offers **STUDENT** or **PROFESSOR**; it never creates staff or admin accounts. Professor registration requires a department selected from the eight controlled Faculty/department codes. Every new Professor account starts **Pending Verification**. A pending Professor can place ordinary orders and open `/professor/settings` to see their name and department and change only their student-delivery preference. Older accounts without a department can select one there once. Neither a preference nor an account role creates an approved managed professor profile, makes the professor selectable by students, or enables **Deliver to Me**. Only Blue and Silver staff can verify or reject the request, then link a verified login to an active managed profile with the same email. The profile still needs approval for self-delivery, and student selection additionally needs a Faculty and acceptance enabled. A linked professor can control acceptance from their settings. Each profile can link to one account. Use a trusted server shell to provision a **SHOP_STAFF** or **ADMIN** account: `python -m flask --app wsgi:app create-privileged-user --role SHOP_STAFF --shop-id ID` (or `--role ADMIN`). Provision one staff account for each of Blue and Silver Bookstore, CHALECOSPOT, Iced Design and Prints, and Pixels Print and Press after creating those shops; the command prompts for a hidden password and never seeds a shared password. Existing admin shop assignment remains available, and unassigned staff cannot access shop orders. The trusted CLI can still link a professor directly with `--role PROFESSOR --professor-id ID`, but that account remains pending until Blue and Silver verifies it. Logout uses a CSRF-protected POST form.

Shop staff use the dedicated `/auth/shop-login` page: choose their assigned shop, enter their staff email or name, and provide their password. This page is intentionally absent from the landing page and student/professor navigation; give the URL directly to staff. It accepts only active `SHOP_STAFF` accounts assigned to the selected shop, and access to shop features remains role-protected. Staff names must be unique within a shop to be used as a sign-in identifier; email always identifies one account. Staff accounts are provisioned through the trusted CLI and assigned by an admin, never through public registration. The earlier Blue and Silver sign-in URL still works for existing bookmarks but is no longer linked from the general login page.

For a **local development** Blue and Silver staff login that asks for only a name and password, run `python -m flask --app run.py create-blue-staff --name "Blue and Silver Bookstore"` after the shop exists. The command prompts privately for a 5–8-letter password; it does not put a credential in source code. Select Blue and Silver on `/auth/shop-login` and enter the staff name and password. The account is assigned to Blue and Silver and cannot be reassigned to another shop. Its internal unique email identifier is not part of the login or staff UI. This short-password provisioning path is disabled in production; use the trusted `create-privileged-user` command with a stronger password there.

After logging in, students can open `/shops` to search active shops and view `/shops/<id>` for details and a price table. Admins use `/admin` to reach management pages. `/admin/shops` retains the existing shop editor for creating/editing or activating/deactivating shops, choosing services, setting paper-size/color prices and rush/delivery fees, and assigning existing staff accounts. `/admin/staff` lists Shop Staff accounts and lets an admin assign, reassign, or unassign each from one shop, except that a name-only Blue and Silver account stays assigned there. These changes take effect on the staff member's next request. No user role is changed through assignment. Assigned staff see only their shop at `/shop` and can open `/shop/manage` to update its description, address, hours, services, prices, fees, and public photo. Staff cannot edit another shop or its registered name, map coordinates, active status, or staff assignments. Uploaded JPEG, PNG, or WebP photos are validated, resized to at most 1024 pixels per side, and stored with the shop record; the public directory, shop detail, map card, and circular map pin use the image. The shop's `Proceed` action becomes available once the student has a configured file.

Students can switch from the shop list to `/shops/map`. The map uses the Google Maps JavaScript API as a geographic background and shows only active registered shops with valid stored coordinates. Its search filters registered shop names on the server; it does not use Google Places or external business search. Selecting an application shop pin or shop card opens the custom Prints On Demand panel with active/available status, address, hours, enabled services, configured fulfillment methods, current prices, and applicable fees. Google's base-map place icons are not clickable. **Proceed** opens the existing shop detail and order path, where checkout remains authoritative for pricing. Shops without coordinates remain in list view. Admins can enter or clear a confirmed latitude/longitude pair in the existing shop editor; values must be within latitude -90 to 90 and longitude -180 to 180, with up to fifteen decimal places.

For a local interactive map, enable the **Maps JavaScript API** in your Google Cloud project, create a browser API key, and set `GOOGLE_MAPS_API_KEY` in your ignored `.env` (or process environment). Never commit a real key. Local development uses Google's development map ID unless `GOOGLE_MAPS_MAP_ID` is set; use a map ID belonging to your project in production. Restrict the production browser key to the application's allowed website referrers and the Maps JavaScript API in Google Cloud. The map page sends the site's origin as referrer for that key restriction. When no key is configured or Maps fails, the page keeps its shop cards and prices available and links to list view. **Use my location** asks for browser permission only after a click, places a one-time indicator on the map when granted, and does not send coordinates to Flask or store them. Browser geolocation may require localhost or HTTPS.

The four development seed shops use user-provided coordinates recorded as the verified locations for those sample records. Reseeding refreshes only the coordinates of matching sample rows, while preserving their other fields and leaving other shops unchanged. Once staff save confirmed shop details, that shop is no longer treated as a seed record and reseeding cannot change its coordinates. Administrators can continue to configure coordinates for all other shops.

Students can open `/files` from `/student`, then `/files/upload` to store one document at a time. The detail page confirms the filename, byte size, and upload time. It also offers an authorized download, configuration, and deletion. Configuration supports Letter, Legal, A4, A3, A2; grayscale or color; print count 1–999 by default; and rush printing. One active configuration is saved per file. Upload/configuration alone does **not** submit an order. Only the owner may list, view, configure, or delete their file; assigned staff may download it only through an order for their own shop. Once a file belongs to an order, deletion is blocked so its private bytes remain available. The same file may intentionally be used for a later reprint order.

To place an order, upload and configure files in the private library, then use a file detail page or an active shop page to open `/orders/new`. Choose a shop and up to **20 distinct configured files**, using **Add files** to select more. Each file has independent paper size, color, print count, and rush settings. Uncheck a file or use **Remove from order** to remove it from the draft without deleting the upload. At least one file is required; `ORDER_MAX_FILES` sets the central limit. Choose exactly one fulfillment method offered by the shop: **Professor Delivery** (Blue and Silver Bookstore only), **Scheduled Pickup** (requested date and time slot), or **Delivery** (recipient name, phone, address, requested date and time slot). Students select an active, approved, accepting professor with an assigned Faculty; that profile supplies the Faculty automatically. Professors ordering for themselves use their linked profile and select a Faculty without a recipient dropdown. The professor's managed details appear at review; students never enter a professor email or Faculty. Checkout prices each item from `PrintPrice`, adds the shop's `RUSH_PRINTING` fee once if any item requests rush, and adds the shop's configured `DELIVERY` fee once for delivery. Pickup and professor fulfillment have no fulfillment fee. Browser-submitted prices and totals are ignored; a submitted delivery-fee field is rejected. The server rechecks the quote, fulfillment details, eligibility, and fee at placement. Any change since review requires confirmation again.

The completed order receives a unique reference such as `POD-2026-A1B2C3D4E5F6` and can be opened at `/orders/<reference>` by its owner. One `OrderItem` references each selected private upload and stores its file name, print settings, unit price, and line total. `Order` stores the shop name, subtotal, one rush fee, one delivery fee when applicable, fees total, currency (`PHP`), total, and fulfillment snapshot, including professor and Faculty for Professor Delivery. Placement commits the order and all items together. Later price, fee, shop, library, or professor changes do not alter these snapshots. Existing one-file and multi-file orders remain readable. A legacy pending order without a destination can still select an eligible professor; a new pickup or delivery order cannot switch fulfillment after placement. Professor selection records the intended physical recipient: **no file or email is sent**. New orders begin at `PENDING_PAYMENT` until payment is independently recorded as paid and staff starts processing.

Scheduling uses the server's `Asia/Manila` date, independent of the browser timezone. `PICKUP_LEAD_DAYS` (default 1) and `DELIVERY_LEAD_DAYS` (default 2) set the earliest request date; both methods have a 30-day window by default through `PICKUP_MAX_DAYS` and `DELIVERY_MAX_DAYS`. `PICKUP_TIME_SLOTS` and `DELIVERY_TIME_SLOTS` are configurable `HH:MM-HH:MM` tuples in `app/config.py`; the defaults are 10–11, 11–12, 13–14, 14–15, and 15–16. A slot must fit the selected shop's stored opening and closing times. This is a request schedule, without per-day closure data or capacity reservations. Admins enable the existing `PICKUP` or `DELIVERY` service and set the `DELIVERY` fee in `/admin/shops`. Delivery requires both enabled service and configured fee. **Delivery represents a requested delivery workflow; no Lalamove booking or other courier booking is automatically created.**

On the order detail page, choose **Onsite payment** to record a pending payment and see the configured counter instructions. Manual **Online payment** requires an enabled flag and nonempty public instructions, account name, and destination; the option stays unavailable if any detail is missing. These values can come from `ONLINE_PAYMENT_ENABLED`, `ONLINE_PAYMENT_INSTRUCTIONS`, `ONLINE_PAYMENT_ACCOUNT_NAME`, `ONLINE_PAYMENT_DESTINATION`, and `ONSITE_PAYMENT_INSTRUCTIONS` in the environment, or an admin can save a complete public-facing override at `/admin/payment`. An optional `PAYMENT_QR_IMAGE_URL` environment setting displays a public payment image alongside those details. Use an HTTPS image URL or a public `/static/` image path (PNG, JPEG, WebP, or SVG); unsafe schemes and private paths are ignored. Leave the setting empty for an instructions-only state. The QR setting is deployment-managed, not editable by students or in the admin payment form. After choosing online payment, the page shows the order reference, stored itemized total and currency, and configured transfer details. Enter a 4–120 character payment reference to move the payment from `PENDING` to `SUBMITTED`; surrounding and repeated whitespace is normalized and unsafe characters are rejected. This is only a claim awaiting manual verification; it does **not** prove funds were received, mark the payment `PAID`, or change the order's `PENDING_PAYMENT` status. A repeated identical submission is harmless; a different reference or method change after submission is rejected. Use fictional details for development; do not commit live account details or QR images. No receipt upload or gateway integration exists.

The same `/orders/<reference>` page confirms the stable order reference, shop, total, intended professor when selected, payment method/status, order status, and current next step. Its **Order tracking** section shows order creation, the recorded payment state, any actual shop-processing transitions, and the current order state. It uses stored order, payment, and processing timestamps; an unrecorded step has no timestamp. Refreshing the page creates no new order, payment, or event. Only the order owner can view it.

Students and professors can open **Order History** from their account navigation. `/orders` lists only the signed-in owner's orders, newest first, 20 per page, with optional order-status and payment-status filters. Each row uses the stored order reference, shop-name snapshot, creation time, total, status, payment state, and destination, including the Faculty for Professor Delivery; selecting a reference opens the owner-only detail page. Orders remain in history if a shop or professor later becomes inactive or pricing changes. An order with no payment is labeled “Not selected,” and `SUBMITTED` means awaiting verification, not paid.

Assigned **SHOP_STAFF** users open `/shop` and follow the shop-orders link to `/staff/orders`. The list shows only their shop's orders. Each detail page shows immutable print-price and professor/Faculty snapshots, payment state, and a secure download for files attached to that order. Processing actions are CSRF-protected POSTs. Ordinary orders use `PENDING_PAYMENT` → `PROCESSING` → `READY` → `COMPLETED`; Blue and Silver Professor Delivery inserts `DELIVERED` between `READY` and `COMPLETED`. The first step requires the payment record to already be `PAID`, and every later step rechecks that state. Submitted/rejected online references and pending onsite payments cannot start processing. Processing timestamps, including the physical handoff, appear in owner tracking. Payment verification never automatically starts processing.

Only staff assigned to **Blue and Silver Bookstore** can open `/admin/professors` to verify pending Professor accounts, reject requests, link verified accounts, and manage names, normalized unique emails, department, controlled Faculty (MITL, CAS, ETYCB, CCIS, CHS, GE, IECELL, SHS), office, active state, approval, and student delivery acceptance. Admins, other shops, students, and professors receive 403 on these routes. Verification and profile linking are separate actions. Students see only verified, linked, active, approved, accepting professors with a Faculty; the selected professor determines the Faculty and students cannot override it. A verified linked professor with an active, approved profile may choose a Faculty for their own delivery without a recipient dropdown, even with student acceptance off. A linked professor can also toggle their own acceptance at `/professor/settings`. Only Blue and Silver staff can change a verified name or managed profile identity; the Professor settings page does not expose these fields. Existing orders keep their recipient and Faculty snapshots after edits or deactivation. Older professor profiles without a Faculty must be assigned one by Blue and Silver staff before new student selection. No electronic file is sent to the professor.

**Professor Delivery requires the configured manual online-payment method.** The backend rejects onsite payment, and the order page shows the online-only requirement. After payment is verified, assigned Blue and Silver staff advance `PENDING_PAYMENT` → `PROCESSING` → `READY` → `DELIVERED` → `COMPLETED`; the `DELIVERED` step records a physical handoff time and appears in owner tracking. Other fulfillment methods keep their existing transitions. No automatic email, gateway transaction, or physical-delivery proof is generated.

Admins and assigned **SHOP_STAFF** can open `/payments/verification` to review only submitted online references. Admins see all shops; staff see only their assigned shop. The review page shows stored order/payment amounts, reference, and submission time. After independently checking receipt of funds, a reviewer can mark the payment `PAID` or reject it with a required reason (maximum 500 characters). A guarded update prevents a stale second review from overwriting the first. The payment keeps the reviewer, review time, and rejection reason; students see a rejection reason on their own order detail but never the verifier identity. Onsite payments are excluded. QR display and reference submission do not automatically verify payment, and there is no payment gateway or notification integration. No new environment settings are required.

**Pricing limit:** Stage 3 rates are presented as per-page/print-unit rates, but Stage 4 does not establish a trusted page count inside PDF or Office files. Checkout uses the student's print count as the number of billed print units and does not inspect document pages. This rule needs reconciliation before real payment. Local seed rates remain sample values and are labeled as such at review. Manual verification is an authorized human decision, not a gateway confirmation.

Private local uploads default to ignored `instance/uploads`, outside `app/static`. `UPLOAD_STORAGE_ROOT` selects another private root for development/testing; if it is inside the repository, add that custom path to `.gitignore`. `UPLOAD_MAX_SIZE` sets the maximum file size in bytes (default **16 MiB**) and the request cap adds 64 KiB for multipart form overhead. `UPLOAD_MAX_QUANTITY` changes the print-count ceiling (default **999**). Supported extensions are PDF, DOC, DOCX, PPT, PPTX, JPG, JPEG, and PNG. The server checks the extension, declared MIME type, and a recognizable file signature or OOXML ZIP structure. This is a screening measure, not a malware scan or complete document parser: legacy DOC/PPT share an OLE signature, and valid-looking content can still be malicious. Uploaded bytes live outside the database under random keys; metadata and SHA-256 live in the database. The current adapter is local and **production uploads are refused** until a durable private adapter is configured. Do not use an ephemeral Render filesystem for real uploads.

For development data only, run `python -m flask --app wsgi:app seed-sample-shops` explicitly after `db upgrade`. It adds four sample shops based on the PDF names, sample services, prices for Letter/Legal/A4/A3/A2 in grayscale and color, and sample rush/delivery fees where relevant. It is idempotent by shop name, refreshes the verified coordinates only for existing matching sample records, preserves their other data, and refuses to run in production. The seed amounts and addresses are **sample values, not approved business rates**; seeded pages label them as sample. Assigned staff or admins can replace prices and fees through the UI without changing code.

For fictional professor data, run `python -m flask --app wsgi:app seed-sample-professors` explicitly after `db upgrade`. It adds two active, approved professors plus unapproved and inactive examples using `example.edu` addresses, with sample Faculty values and student-delivery acceptance OFF by default. The command is idempotent by email, leaves existing records and approvals unchanged, and refuses to run in production. These records are development-only sample data; Blue and Silver staff can manage them at `/admin/professors`. They do not appear in student selection until a verified account is linked and delivery acceptance is enabled.

`DATABASE_URL` overrides the local SQLite default; `postgres://` URLs are normalized to `postgresql://`. `FLASK_ENV` accepts `development`, `testing`, or `production`. `TESTING=true` also selects the isolated in-memory SQLite configuration; it cannot be enabled with production. Production requires a PostgreSQL `DATABASE_URL` and a random `SECRET_KEY` of at least 32 characters, rejects debug mode, enables secure session cookies, and does not silently use local defaults. Configure trusted hosts, HTTPS/HSTS, and durable private uploads before deployment. Object-storage names in `.env.example` are reserved for a later adapter and are not used yet. Never commit `.env`, passwords, payment receipts, uploaded documents, or production data.

## Deployment target and storage

Source control will use GitHub and deployment will target Render with PostgreSQL. Runtime settings and secrets come from environment variables. The WSGI entry point is ready for `gunicorn wsgi:app` on Linux. Render service settings and release/migration steps will be finalized before deployment.

Local uploads are for development only and must not be assumed durable in production. The storage interface can be replaced with private persistent/object storage without changing file routes. Cleanup of abandoned uploads and recovery after a storage/database failure remain future operational work. See the [storage and deployment specification](docs/project-specification.md#storage-and-deployment).

## UI/UX reference

**[PrintsOnDemand Mobile.pdf](docs/references/PrintsOnDemand%20Mobile.pdf)** is the primary student UI reference. [UI reference notes](docs/ui-reference.md) record the review of all nine pages. Stages 6–11 added approved-professor selection, manual payment, tracking, staff processing, admin management, and order history. Stage 12 applied the mobile-first visual design.
