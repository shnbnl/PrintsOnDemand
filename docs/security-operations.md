# Security controls and deployment

Passwords remain salted Werkzeug scrypt hashes. Passwords, session tokens, database
connection strings, and external-tool stderr must never appear in audit output.
Do not convert hashes to plain text. Existing password hashes remain compatible.

## Deploy this update

Back up the existing database and private upload directory first. In the deployed
project's activated virtualenv, run:

```bash
git pull --ff-only origin main
python -m flask --app run.py db upgrade
```

The migrations add `auth_sessions` and `rate_limit_buckets` and, on PostgreSQL,
enable private-row policies. They do not delete customer orders or documents.
**Run the migration before reloading the web app.**
Existing login and remember-me cookies are intentionally rejected after this
update, so every account must sign in again. Reload the PythonAnywhere web app.

## Authentication and browser controls

- Every login has a random 256-bit credential. Only its SHA-256 digest is stored
  server-side. Numeric user IDs are not accepted as login credentials.
- Logout deletes the current server-side credential, clears the Flask session and
  remember cookie, and returns `Clear-Site-Data` for browser cache, cookies and
  origin storage. That browser header requires HTTPS and browser support; server
  revocation works independently. No app authentication token is stored in browser
  Local Storage or Session Storage. Other devices stay logged in.
- Successful account deletion uses the same browser cleanup. Invalid or expired
  sessions clear cache and origin storage and expire the authentication cookies;
  they preserve the fresh anonymous session cookie needed for login-form CSRF.
- Ordinary sessions expire after 30 minutes idle or 12 hours absolute. Customer
  remember-me credentials expire after 7 days idle or 14 days absolute, even if
  used repeatedly. Staff/admin sessions cannot use remember-me. Password changes,
  deactivation, or deletion also invalidate the old credentials.
- Dynamic responses use `private, no-store`; static assets can still be cached.
- CSRF remains enabled globally for POST and other unsafe methods, including
  logout, payment review, account deletion, uploads, and order actions.
- Shared database counters limit login attempts to 100/IP/15 minutes and
  20/identifier/15 minutes across both login forms and the legacy Blue staff form.
  Registration is limited to 20/IP/hour, uploads to 60/account/15 minutes, and
  account-deletion attempts to 20/IP/15 minutes. Invalid CSRF does not bypass the
  counters. A rejection is HTTP 429 with `Retry-After`. Tune these application
  configuration values for measured campus/shared-IP traffic.
- Rate-limit identities are keyed hashes; the counters do not store raw IPs or
  emails. Run `cleanup-security-state` daily to remove expired counters/sessions.
- Form fields have server-side length validation, form-memory/part limits, and
  private file uploads retain their 25 MiB ceiling and content validation. Uploaded
  documents are forced downloads through owner/shop authorization checks.
- CSP restricts framing, plugins, base URLs and form destinations. It does not
  claim to be a script allowlist; Google Maps and existing inline scripts still
  work. Jinja escaping remains the primary HTML injection protection.

## Database row policies

PostgreSQL migration `d82f1b70a631` enables and forces RLS on `orders`,
`order_items`, `payments`, `uploaded_files`, and `print_configurations`. SQLite
does not support RLS; its migration is a no-op and existing route/service
ownership checks remain essential on both backends.

Each transaction receives the server-validated user ID through a transaction-local
setting. Missing identity denies private-row access, and pooled connections cannot
retain the previous transaction's identity. Customers see their own orders/files;
staff see their assigned active shop's orders and attached files; administrators
can read private records. Inserts require customer ownership, including ownership
of an order item's file. Placed item snapshots have no UPDATE policy. Business
rules for prices, status transitions, and payment review remain in the services;
RLS enforces row boundaries, not every editable field.

Account deletion explicitly enables a transaction-local erasure scope after
checking authorization. Self-deletion, administrator deletion, and Blue and Silver
staff deleting a professor can remove the target's history across shops and clear
references in surviving orders/payments. That scope permits cross-shop reads
during deletion; ordinary staff requests do not get it. Shared shop data and other
customers' orders remain intact.

Use a separate non-owner web DB role with `NOSUPERUSER NOCREATEDB NOCREATEROLE
NOBYPASSRLS`, ordinary DML/sequence privileges, and no membership in an administrative
role. Run migrations as the schema owner. Run `security-check` using the **web
role** after migration; it checks RLS flags, named policies, and bypass privileges.
Use separate operator credentials with deliberate RLS bypass for complete backups
and cross-account maintenance. Do not put those credentials in the web process.
The backup CLI must not run with the restricted web role, which cannot see every
customer's files. No CLI request identity or implicit RLS bypass is provided.

Authentication tables and public shop/professor directory tables are not covered
by these policies. The browser never receives database credentials. Because the
server shares a DB role and sets its own identity, these policies defend against
missing row filters; they do not contain arbitrary SQL execution with that role.
Parameterized queries and application authorization remain required.

Optional real PostgreSQL integration tests require an empty, disposable database:

```bash
POSTGRES_RLS_TEST_URL=postgresql+psycopg://TEST_OWNER@localhost/EMPTY_TEST_DB pytest tests/test_postgres_row_policies.py -q
```

The test owner needs permission to create test roles and schemas. Never use the
deployed database: the fixture refuses existing application tables and removes
the objects it creates. These tests have also run against PostgreSQL 18.6 in
PGlite; deployment-specific role provisioning and backup operations still need
verification on the actual host.

## HTTPS on PythonAnywhere

Enable **Web > Security > Force HTTPS**, then reload. Set the deployed environment
or ignored `.env` to use the actual public hostname:

```dotenv
FORCE_HTTPS=true
TRUSTED_HOSTS=decimo.pythonanywhere.com
```

`FORCE_HTTPS` disables debug, enables Secure cookies, redirects HTTP GET/HEAD to
HTTPS, refuses unsafe HTTP requests, and sends HSTS on secure responses. Production
mode enables it automatically and cannot disable it. HSTS is scoped to this host,
without `includeSubDomains` or preload.
Production startup also requires a nonempty `TRUSTED_HOSTS` allowlist.

Set `PROXY_FIX_HOPS` only after confirming the hosting proxy's behavior. It defaults
to 0 (forwarded headers are ignored). If the WSGI environment is already configured
with the external scheme/IP, leave it 0. If a verified single proxy supplies and
sanitizes `X-Forwarded-Proto` and `X-Forwarded-For`, set it to 1. An incorrect count
can permit forged client addresses or HTTPS detection, or cause redirect loops.
The app never trusts forwarded Host headers. Test an HTTPS login and an HTTP
redirect after changing the setting.

The existing `production` profile still requires PostgreSQL and a durable storage
adapter; this update does not silently switch a PythonAnywhere SQLite deployment
to that profile or remove its existing storage guard.

## Database least privilege

Use separate PostgreSQL migration/schema-owner and runtime accounts. Run migrations
as the schema owner. The runtime role should not be a superuser, schema/database
owner, role creator, database creator, or a member of an administrator role.
Give it CONNECT to the app database, USAGE on the app schema, SELECT/INSERT/UPDATE/
DELETE on the app tables, and USAGE/SELECT on the app sequences. Configure the
migration owner's default privileges so future tables/sequences get those same
runtime grants. Do not grant CREATE/DROP or broad administrative capabilities to
the web process. Keep credentials in the host's environment/ignored `.env`, and
restrict network access to the database.

SQLite has no separate database login/role. Restrict the database, its parent
directory, backup directories, and private upload directory to the app's OS
account; do not put them under static/public directories. Apply equivalent host
permissions to WAL/SHM files if SQLite uses WAL mode.

Run the read-only checks using the **runtime credentials**:

```bash
python -m flask --app run.py security-check
```

The command exits nonzero for failed checks and reports HTTPS/cookies, debug,
trusted hosts, CSRF, signing key, password formats, PostgreSQL role flags/schema
ownership, and local encrypted backup freshness. PostgreSQL role memberships,
effective grants, provider settings and off-site recovery still require operator
review. No credentials or grants are changed by the command.

## Encrypted automated backups

Install GnuPG on the backup host; PostgreSQL also needs `pg_dump` compatible with
the DB server. Generate the encryption/recovery key on a separate secure machine,
keep the private key there, and import **only the public key** on the app host.
Set a private `BACKUP_DIRECTORY` and the public key's full 40–64 hex-character
`BACKUP_GPG_RECIPIENT` fingerprint. The command will refuse missing encryption
configuration; it never publishes a completed unencrypted archive.

```bash
python -m flask --app run.py backup-data
python -m flask --app run.py cleanup-security-state
```

`backup-data` snapshots SQLite with its online backup API, or uses a shared
PostgreSQL repeatable-read snapshot and `pg_dump`. It includes the referenced
private documents plus a SHA-256/size manifest. Each document is checked against
its database metadata while it is archived. A file deleted during the backup
causes the backup to fail rather than publish an incomplete snapshot; retry after
traffic/deletions settle, or take the snapshot during a maintenance window.
Unreferenced files, `.env`, source code and signing secrets are excluded. DB-stored
shop photos/QRs are covered by the database snapshot.

Temporary plaintext snapshots live only in a mode-0700 work directory and are
removed on normal completion or handled errors. Completed `.tar.gz.gpg` files
have mode 0600. An abrupt process kill may leave `.backup-*` temporary data; monitor
and remove those directories only after confirming no backup is running. The
backup root must stay private and outside static/uploads.

Add daily **Scheduled tasks** in PythonAnywhere using the actual project and
virtualenv paths, for example:

```bash
cd /home/decimo/YOUR_PROJECT && /home/decimo/YOUR_VENV/bin/python -m flask --app run.py backup-data
cd /home/decimo/YOUR_PROJECT && /home/decimo/YOUR_VENV/bin/python -m flask --app run.py cleanup-security-state
```

Use the scheduler's displayed timezone. Confirm a successful run and monitor its
exit status/log. Schedule `security-check` after backup and alert on failure.
Copy completed encrypted files to a separate private host/bucket using your
provider's supported mechanism. Suggested retention: 7 daily + 4 weekly copies,
adjusted to your document/privacy policy. The app does not silently delete old
backups or configure an off-site account. A backup on the same host alone does not
protect against loss of that host. Scheduling, alert delivery and off-site storage
need the operator's host/provider access and are not activated by a Git push.

## Recovery drill

On the recovery machine with the private recovery key available to GnuPG:

```bash
python -m flask --app run.py verify-backup /private/path/prints-backup-TIMESTAMP.tar.gz.gpg
```

This decrypts into a private temporary directory, verifies every archived file and
manifest entry without extracting paths, then removes the temporary data. It does
not overwrite the running application. Test recovery regularly in an isolated
environment: decrypt the trusted archive, restore `database.sqlite3` to a fresh
SQLite path or restore `database.dump` into a new PostgreSQL database with
`pg_restore`, and restore `uploads/*` into a new private upload root. Match the app
revision/schema to the snapshot and validate users, orders and document downloads.
Before allowing login against a restored DB, delete all rows from `auth_sessions`
and `rate_limit_buckets` so a restore cannot revive revoked login credentials.
Never restore over the live database to test recovery. Securely retain signing
secrets and the recovery private key separately from application backups.

## Regression coverage and limits

The automated suite checks owner-only order/file access, staff shop isolation,
payment/price tampering, privileged role boundaries, CSRF, hashed passwords,
copied-cookie replay after logout, idle/absolute expiry, login/signup rate limits,
HTTPS/proxy handling, and backup integrity/isolated SQLite recovery. The migration
is checked against an existing populated schema. SQLite/PostgreSQL counter upserts
are supported; PostgreSQL dump/privilege operations must also be exercised on the
actual PostgreSQL deployment. Document signature/type validation is not an
antivirus scanner; no malware scanning service has been connected by this change.

References: [OWASP session management](https://cheatsheetseries.owasp.org/cheatsheets/Session_Management_Cheat_Sheet.html),
[Flask security](https://flask.palletsprojects.com/en/stable/web-security/),
[Flask proxy handling](https://flask.palletsprojects.com/en/stable/deploying/proxy_fix/),
[PythonAnywhere Force HTTPS](https://help.pythonanywhere.com/pages/ForcingHTTPS).
