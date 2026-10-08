# Phase 1 security audit (2026-10-08)

Scope: local Flask code, routes, forms, models, storage, tests, migrations, and documented deployment settings. No live PythonAnywhere configuration, web-server rules, database contents, or external object storage was available for inspection.

## Security map

| Area | Server-side boundary |
| --- | --- |
| Public auth | `/auth/register`, `/auth/login`, `/auth/shop-login` use Flask-WTF CSRF, form validation, password hashes, generic login errors. `/auth/logout` is POST with global CSRF. |
| Customer | `/files`, `/orders`, `/checkout`, `/account` require Student or Professor. File/order reads and writes select by `current_user.id`; checkout draft includes `user_id` and rechecks staged-file ownership. |
| Shop Staff | `/shop/manage`, `/staff/orders`, and `/payments/verification` require Shop Staff (payment review also permits Admin) and scope staff reads/writes to the assigned shop. Professor management additionally requires staff assigned to Blue and Silver Bookstore. |
| Admin | `/admin/staff`, `/admin/shops`, `/admin/payment` require Admin. Admin shop/staff mutations validate the target role/object. |
| Private files | Random storage keys outside `app/static`; downloads check exact file owner or exact owned/assigned-shop order and return attachments with no-store. |
| Production | `FLASK_ENV=production` requires PostgreSQL and a stable 32+ character secret, rejects debug, sets Secure cookies, and currently refuses local uploads. |

Global `CSRFProtect` covers all POST routes, including form and direct-POST actions. Route and service tests cover customer, professor, staff, admin, cross-customer, cross-shop, and unauthenticated direct URL access. This is local verification, not a penetration test.

## Findings and changes

| Severity | Finding | Status |
| --- | --- | --- |
| Medium | Login, registration, account deletion, uploads, and order placement had no durable abuse limits. | Fixed with a database-backed counter table. Run `flask db upgrade` before deploying this code. |
| Medium | A JPEG/PNG magic header alone could pass private-upload validation; DOCX/PPTX ZIP metadata did not bound total extracted size or reject unsafe member names. | Fixed with real Pillow decoding, a 20-megapixel ceiling, and OOXML entry/count/size/path checks. |
| Low | Protected HTML pages could be cached by the browser. | Fixed with `Cache-Control: private, no-store` on protected blueprints. |
| Low | HSTS and device Permissions-Policy headers were absent. | Fixed: production HSTS `max-age=31536000`; camera and microphone denied, while map geolocation remains available. |
| Low | Security events were sparse. | Added secret-free login, registration, account-deletion, staff-assignment, professor-verification, and payment-decision logs. Existing payment rows also record reviewer and time. |
| Medium | Public registration returns different success/duplicate outcomes, allowing account-existence inference. | Remains. Eliminating this cleanly requires an email verification or invitation flow. Login failures are generic and missing/inactive users now perform a dummy password-hash check. |
| Medium | DOC/PPT use an OLE signature check; Office rendering is not malware scanning or a hardened sandbox. | Remains. Restrict converter privileges and resources on the deployment host, and add scanning if untrusted documents are accepted at scale. |
| Informational | No password-reset/recovery flow exists in the repository, despite the audit brief listing one. | Not applicable to token-expiry/reuse testing; assess any separately deployed reset service. |
| High, deployment-dependent | The brief describes PythonAnywhere with SQLite, but repository production mode requires PostgreSQL and refuses local uploads. A live instance using the default development mode would have debug enabled and insecure cookies. | Requires production verification; the live environment was not inspected. Do not infer the live mode from the brief. |

## Implemented limits

All counters are shared through the database, use HMAC keys rather than raw email/name/IP, and return `429` with `Retry-After` and no-store. Client IP uses WSGI `REMOTE_ADDR`, not caller-controlled forwarding headers.

| Endpoint | Limit | Purpose |
| --- | --- | --- |
| Both login forms | 10 attempts per identifier per 15 minutes; 60 per IP per 15 minutes | Password guessing and spray resistance. |
| Registration | 10 valid submissions per IP per hour | Automated account creation. |
| Account deletion | 5 confirmed attempts per account per hour | Password guessing against a destructive action. |
| Library and checkout uploads | 100 accepted-form requests per account per day | Storage and parser abuse; ordinary 20-file checkout remains under the cap. |
| Legacy and guided order placement | 30 valid-form requests per account per day | Repeated order creation. |

Recommended, not implemented: add a separate modest limit to staff/admin destructive actions (for example, 60 per actor per hour) after confirming real operational volume. Password-reset limits are inapplicable until a reset flow exists. These fixed-window limits are an abuse-control layer, not a replacement for reverse-proxy limits or monitoring.

## Production checks before release

1. Determine the actual `FLASK_ENV`, `FLASK_DEBUG`, `DATABASE_URL` driver, secret persistence, HTTPS termination, cookie flags, backup policy, and private-upload directory/adapter on PythonAnywhere. Resolve the SQLite/PostgreSQL and local-storage mismatch deliberately.
2. Apply migration `b842c0e16a7f` with the deployed database and verify rate-limit counters work across workers. Confirm `REMOTE_ADDR` identifies clients correctly behind the host proxy, or configure a trusted proxy at the WSGI boundary.
3. Verify HTTPS and the HSTS header from the public URL. Verify private uploads are outside every web-served directory and that downloads require authorization.
4. A Content-Security-Policy was not added: the app currently has an inline style and Google Maps dynamically loads scripts/images. Inventory those origins and test a report-only policy before enforcement. Add trusted-host validation once deployed hostnames are known.
5. Review PythonAnywhere web-server and LibreOffice/AbiWord process limits, temporary-directory isolation, logging retention, backups, and incident alerting. No live settings were available in this local audit.
