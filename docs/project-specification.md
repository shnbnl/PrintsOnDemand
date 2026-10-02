# Project specification

## Scope and implementation boundary

Prints On Demand connects students with printing shops and supports document submission, printing, payment, and fulfillment. Stage 0 provides the specification and empty repository structure only. All behavior described here is a requirement or proposed design, not existing functionality.

The required stack is Python 3.12, Flask, SQLAlchemy, Flask-Migrate, Flask-Login, Flask-WTF/CSRF, PostgreSQL, Jinja, vanilla JavaScript, CSS, pytest, and Gunicorn on Render. GitHub will host source control.

## Student journey

1. Register or log in, search shops, and inspect information, opening hours, and pricing.
2. Choose a shop and upload documents. A successful upload confirms storage/validation only; it does not submit an order or prove payment.
3. Choose quantity, paper size, grayscale/color, and regular or rush printing.
4. Choose pickup/scheduled pickup or delivery and select Myself or Professor as recipient.
5. Review the server-calculated price and choose online or onsite payment.
6. Submit the order. Only a successful persisted order receives an order confirmation and unique reference number.
7. View payment information and order progress independently, and find the order again in order history.

Exact screen boundaries and navigation must be reconciled with the PDF before UI implementation.

## Roles and authorization

| Role | Access boundary |
| --- | --- |
| Student | Own profile, uploads, orders, receipts, tracking, and history only. |
| Shop Staff | Incoming orders and files for shops to which staff are assigned; payment verification and authorized fulfillment updates. |
| Admin | User, shop, professor, approval, and pricing management; order monitoring through authorized routes. |

Check permissions on the server for every request, including downloads and status changes. Hiding a button is not authorization. Registration must not allow a student to assign themselves staff or admin privileges.

## Direct-to-Professor

- The recipient selector offers **Myself** or **Professor**.
- Professor shows a searchable dropdown containing only professors who are both active and approved for Direct-to-Professor.
- Selection automatically displays the professor's name, department, email, and office/room. These details come from the managed professor record and are read-only for the student.
- An optional note is allowed. There is no manual receiver-email field or email override in the submission API.
- Validate the selected professor's ID, active state, and approval on the server at submission, even if the dropdown already filtered it.
- Admin can approve or revoke permission. Proposed rule: recheck approval before dispatch; if revoked, stop professor dispatch and require an authorized recipient change or cancellation, preserving the audit history.
- Preserve a snapshot of the selected recipient details on an order for historical accuracy; a snapshot does not override revoked permission.

Whether professor fulfillment means a physical handoff, electronic delivery, or both remains to be clarified before implementation. Do not implement automated email sending based on the term alone.

## Payments

Support **Online Payment** and **Onsite Payment**. Initially, shops will use configurable online payment instructions/QR codes, with optional receipt upload. Staff will verify payment manually. Do not integrate real GCash/Maya APIs yet.

Instructions and QR references belong in managed database/settings records, not duplicated template constants. Receipts are private files. Uploading a receipt never verifies a payment automatically, and an optional receipt must not be the only way to verify payment.

Store payment method and payment state independently from fulfillment status. Proposed payment states are pending, verified, and rejected, with verifier and timestamp recorded. This allows an onsite-payment order to progress through printing while payment is still pending. The exact onsite collection point, cancellation/refund rules, and who may override a payment decision must be settled before payment implementation. Record onsite collection explicitly before treating an order as paid.

## Order status vocabulary

Use these exact order status identifiers:

| Status | Meaning |
| --- | --- |
| `SUBMITTED` | The order was successfully persisted and assigned a reference number. |
| `PAYMENT_PENDING` | The order is awaiting payment or manual verification. |
| `PAYMENT_VERIFIED` | An authorized staff member confirmed payment. |
| `PRINTING` | Production is underway. |
| `READY_FOR_PICKUP` | Printing is ready for collection. |
| `OUT_FOR_DELIVERY` | The order has been dispatched for delivery. |
| `SENT_TO_PROFESSOR` | The order has been dispatched to the approved professor; receipt is not yet confirmed. |
| `DELIVERED` | Handoff/receipt has been confirmed. |
| `COMPLETED` | Fulfillment and applicable payment requirements are satisfied. |
| `CANCELLED` | The order was cancelled with a recorded reason. |
| `REJECTED` | The shop rejected the order with a recorded reason. |

These statuses are not a single mandatory linear sequence. Proposed paths for later validation:

- Online payment: `SUBMITTED` → `PAYMENT_PENDING` → `PAYMENT_VERIFIED` → `PRINTING`.
- Onsite payment: `SUBMITTED` → `PAYMENT_PENDING` → `PRINTING`, subject to the shop's approved collection policy.
- Self pickup: `PRINTING` → `READY_FOR_PICKUP` → `COMPLETED` after collection and payment requirements are met.
- Self delivery: `PRINTING` → `OUT_FOR_DELIVERY` → `DELIVERED` → `COMPLETED`.
- Professor fulfillment: `PRINTING` → `SENT_TO_PROFESSOR` → `DELIVERED` → `COMPLETED`, with dispatch/handoff details finalized before implementation.

When payment is verified after printing begins, update the separate payment record and history without moving fulfillment backward to `PAYMENT_VERIFIED`. Display payment state alongside order status. Record each order transition with actor, timestamp, and reason when relevant. Confirm the full allowed transition matrix, cancellation/rejection windows, and receipt evidence before building status controls; never accept an arbitrary status supplied by the browser.

## Pricing

Final prices are undecided. Store prices and supported options in database/settings records, scoped to shops as needed. Any development seed prices must be clearly marked sample/demo values and kept out of production defaults.

Calculate and validate prices on the server using trusted document/option data and current configuration. Use decimal money values, not binary floating-point arithmetic. Preserve the accepted line items, quantities, currency, and total on the order so later price edits do not rewrite order history. Revalidate a quote at submission and require confirmation if its price changed.

Before implementation, decide supported paper sizes and file formats, page-count validation, copies versus pages, rush/delivery fees, scheduling capacity, currency, and rounding. Do not invent finalized prices in Stage 0.

## Proposed application structure and records

The Flask application factory and extensions will be added in Stage 1. Blueprints will organize authentication, student, staff, and admin routes. Services will own pricing, submission, payment verification, and transition rules so routes remain readable. Storage adapters will isolate file handling from business rules.

Likely database records include users/roles, shops/staff assignments, professors/approval history, pricing/settings, uploaded-file metadata, orders/items, recipient and price snapshots, payments/receipts, and status history. These are design candidates, not an implemented schema.

## Storage and deployment

- Store file metadata and opaque storage keys in PostgreSQL; avoid using client filenames as physical paths or public URLs.
- Define a small storage interface for saving, authorized retrieval, and deletion. Start with a private local adapter for development; allow a persistent/object-storage adapter for production.
- Keep local uploads outside `app/static/` and exclude them from Git. A Render application's local filesystem must not be treated as permanent storage.
- Production must choose and configure durable private storage before accepting real uploads. Any signed download links must be short-lived and issued only after authorization.
- Plan cleanup of abandoned uploads and failed submissions so files and orders cannot silently diverge. Set retention, deletion, backups, and recovery policy before launch.
- Use environment variables for environment selection, signing secrets, PostgreSQL connection, upload limits, and storage credentials. Fail clearly on missing required production configuration; never fall back to demo secrets or temporary storage silently.
- Add the Gunicorn command, Render service configuration, migration/release steps, and health checks after the application exists. Production must use HTTPS, secure cookies, and disabled debug mode.

## Security requirements for later stages

- Hash passwords with a maintained password-hashing implementation; never store plaintext passwords.
- Apply CSRF protection to state-changing forms and JavaScript requests.
- Enforce authenticated role access, shop assignment boundaries, order ownership, and file ownership server-side.
- Sanitize display/download filenames; use generated storage keys; reject traversal and disallowed file types. Check file content as well as extensions and enforce configured request/file size limits. Define malware scanning/quarantine handling before production.
- Serve documents and receipts privately through authorized access. Avoid logging document contents, credentials, or receipt details.
- Validate printing options, professor eligibility, payment updates, prices, and status transitions on the server.
- Escape user-controlled content in templates, including notes and filenames.
- Keep secrets out of Git and use separate development, test, and production databases/storage.

## Later verification plan

Use pytest for meaningful tests of role and ownership boundaries, CSRF, private downloads, upload rejection, professor eligibility/revocation, server-side price calculation, order persistence/confirmation, payment verification, and valid/invalid status transitions. Test migrations and storage adapters against isolated resources. No application tests are claimed or implemented in Stage 0.

## Decisions still needed

- Obtain and review the actual UI reference PDF.
- Finalize prices, currency, printing options, page-count rules, scheduling, and delivery coverage.
- Define professor dispatch/receipt semantics and how affected orders are handled after a revocation.
- Approve the status transition matrix, onsite collection point, cancellation, rejection, and refund policies.
- Select production storage and define retention, upload limits/formats, and recovery procedures.

These decisions do not prevent completing the Stage 0 repository foundation.
