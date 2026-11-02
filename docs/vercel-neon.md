# Vercel Hobby and Neon Free

This prepares the database connection for a personal, non-commercial demo using
Vercel Hobby and Neon Free PostgreSQL. It does not create accounts, deploy the
app, copy existing SQLite data, or enable production document uploads.

**The full printing workflow still needs durable private file storage.**
The current production guard deliberately rejects uploads until that exists.
Changing an environment variable cannot implement the missing storage adapter.

## 1. Create the free database

Create a Neon project on its **Free** plan, either directly in Neon or through
Vercel Marketplace. Keep the database and Vercel function regions close together.
The free database has usage/storage limits; check them in the provider dashboards.

Use a separate Neon branch/database for previews. Preview deployments must not
write to the production database. Do not put database URLs in source control,
browser JavaScript, screenshots, or chat messages.

Neon provides a direct connection and a pooled connection (whose hostname includes
`-pooler`). Keep the provider's `sslmode=require` and any `channel_binding` options.
The app accepts `postgres://`, `postgresql://`, and `postgresql+psycopg://` URLs and
uses the psycopg 3 driver already installed by requirements.txt.

## 2. Initialize the schema from a trusted workstation

Use the **direct schema-owner connection**, not a transaction-pooled web
connection, to run migrations. Keep these owner credentials off Vercel.
In the activated local virtualenv, set these process environment variables using
your own values. The database URL below is only a placeholder:

```powershell
$env:DATABASE_URL = 'postgresql://SCHEMA_OWNER:URL_ENCODED_PASSWORD@DIRECT_HOST/neondb?sslmode=require'
$env:DATABASE_POOL_MODE = 'queue'
$env:FLASK_ENV = 'production'
$env:SECRET_KEY = 'REPLACE_WITH_A_RANDOM_SECRET_OF_AT_LEAST_32_CHARACTERS'
$env:TRUSTED_HOSTS = 'YOUR_PROJECT.vercel.app'
python -m flask --app wsgi.py db upgrade
python -m flask --app wsgi.py check-db
```

Run these commands sequentially and stop if either fails. This creates the schema
in the selected database; it does **not** transfer records from SQLite. Never run
`db init` again or use `db.create_all()` instead of the migration history.
Do not run migrations during function startup or automatically in every preview
build. Run later schema migrations once, before deploying code that needs them.

For existing users/orders, keep the old app and SQLite database intact. Back up
SQLite and its private upload directory, stop writes during cutover, and migrate
the records separately, preserving primary/foreign keys and password hashes.
Verify counts, PostgreSQL sequences, ownership and file references before switching
traffic. A SQLite database file cannot be used as a PostgreSQL database.

## 3. Create a restricted web database login

In the Neon SQL editor, connected as the schema owner to this new database, create
a web role with its own randomly generated password. Replace the sample password
and database name. Do not reuse the schema owner's login:

```sql
CREATE ROLE pod_web WITH LOGIN PASSWORD 'REPLACE_WITH_A_RANDOM_PASSWORD'
    NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT NOBYPASSRLS;
GRANT CONNECT ON DATABASE neondb TO pod_web;
GRANT USAGE ON SCHEMA public, pod_security TO pod_web;
GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO pod_web;
REVOKE ALL ON TABLE public.alembic_version FROM pod_web;
GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO pod_web;
GRANT EXECUTE ON ALL FUNCTIONS IN SCHEMA pod_security TO pod_web;
```

The existing migrations install transaction-local row policies. The web role must
not own tables, bypass row security, or inherit the schema-owner/admin role.
After migrations that add tables/sequences/functions, grant the required new
permissions as the owner. See [Security operations](security-operations.md).

Create privileged application users from a trusted operator shell, using the
existing `create-privileged-user` CLI. Do not expose an account-creation HTTP route
or seed command to work around missing initial accounts.

## 4. Configure the Vercel project

Import the repository and select the **Flask** framework on **Hobby**. The existing
`wsgi.py` exports `app` and is a supported entry point. `.python-version` selects
Python 3.12, `requirements.txt` installs dependencies, and `vercel.json` copies
`app/static` to `public/static` during the build, preserving existing `/static/...`
URLs while Vercel serves the assets from its CDN.

Set these environment variables in Vercel for the intended deployment environment:

| Variable | Value |
|---|---|
| `FLASK_ENV` | `production` |
| `DATABASE_URL` | Neon **pooled** PostgreSQL URL for **pod_web**, retaining TLS options |
| `DATABASE_POOL_MODE` | `null` |
| `SECRET_KEY` | Stable random secret of at least 32 characters |
| `TRUSTED_HOSTS` | Exact project/custom domain hostnames, comma-separated, without schemes |
| `FORCE_HTTPS` | `true` |
| `FLASK_DEBUG` | `0`, or omit |
| `TESTING` | Omit |
| `GOOGLE_MAPS_API_KEY` | Website-restricted key, if using the map |
| `GOOGLE_MAPS_MAP_ID` | Your map ID, if using the map |

Vercel sets `VERCEL=1`; the app then defaults to its production configuration and
refuses development/testing profiles and SQLite. For PostgreSQL it defaults to
`NullPool`: Neon owns the pool rather than every function process retaining a
separate pool. Automatic psycopg prepared statements are disabled in that mode.
Database connections have a 10-second connection timeout and must use TLS on
Vercel. Explicit certificate verification options are retained.

Keep `PROXY_FIX_HOPS=0` unless the actual deployment's forwarded-header behavior
has been verified. If HTTPS requests redirect back to themselves, verify the
trusted proxy chain before changing that setting.

If an integration automatically inserts a database-owner URL, replace it with the
restricted role's pooled URL. Do not upload `.env`, `instance/`, or private files.
`.vercelignore` excludes local data, secrets, tooling and test artifacts from CLI
deployments; real credentials belong in Vercel's environment settings.

## 5. Verify before using customer data

From a trusted workstation, switch `DATABASE_URL` to the **web role's pooled URL**
and `DATABASE_POOL_MODE` to `null`, then run:

```powershell
python -m flask --app wsgi.py check-db
python -m flask --app wsgi.py security-check
```

The database ownership/RLS checks must pass. The storage and backup checks remain
unsatisfied until their separate implementations and operator setup are complete.
`/health` checks process liveness only; it does not prove that the database works.

## Remaining work for a working printing demo

- Implement a **private durable object-storage adapter**, including authorized
  downloads, integrity checks, expiry cleanup, and account-deletion recovery.
  Never use a public bucket for customer documents or `/tmp` as permanent storage.
- Adapt uploads for Vercel's **4.5 MB request/response body limit**. The current
  multipart flow supports up to 25 MiB per file and cannot retain that capability
  through a Vercel Function. Direct-to-private-storage uploads need server-side
  validation before a file is accepted for checkout.
- Arrange Word document rendering outside the function runtime, or use the
  existing PDF fallback. LibreOffice/AbiWord is not bundled with this deployment.
- Schedule cleanup and backups on a suitable trusted operator/worker environment;
  the existing CLI commands are not public web endpoints.

## Provider documentation

- [Vercel Hobby plan and non-commercial use](https://vercel.com/docs/plans/hobby)
- [Flask entry points and static assets](https://vercel.com/docs/frameworks/backend/flask)
- [Python runtime](https://vercel.com/docs/functions/runtimes/python)
- [Function body limits](https://vercel.com/docs/functions/limitations)
- [Database integrations](https://vercel.com/docs/storage)
- [Neon Free plan limits](https://neon.com/pricing)
- [Neon connection pooling](https://neon.com/docs/connect/connection-pooling)
- [psycopg prepared statements and poolers](https://www.psycopg.org/psycopg3/docs/advanced/prepare.html)
