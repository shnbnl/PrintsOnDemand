# Account deletion policy (Stage 24)

Students and professors can open **Account → Delete Account**, review the consequences, cancel, or submit a CSRF-protected form with their current password and an explicit confirmation checkbox. The server derives the account ID from the authenticated session. Staff and admin accounts have no self-service deletion route. A successful deletion logs the customer out, clears the session and remember cookie, and redirects to the public landing page with a confirmation message.

## Ownership audit

The database currently has no notification, token, separate profile-settings, or order-event tables. Order progress is stored as status and timestamps on `orders`. User-linked rows are:

| Relationship | Deletion policy |
| --- | --- |
| `users.id` → `uploaded_files.user_id` | Delete the user's upload metadata and exact private storage keys. |
| `uploaded_files.id` → `print_configurations.file_id` | Delete each uploaded file's configuration. |
| `users.id` → `orders.user_id` | Delete every owned order, including pickup/delivery and professor recipient/Faculty snapshots and status timestamps. |
| `orders.id` → `order_items.order_id` | Delete the order's items before the order. |
| `uploaded_files.id` → `order_items.uploaded_file_id` | Delete the owner's order items before their file metadata. Other users' files are untouched, even if a malformed cross-owner reference exists. |
| `orders.id` → `payments.order_id` | Delete associated payment state, submitted reference, rejection reason, and review timestamp before the order. |
| `users.id` → `payments.reviewed_by_id` | Null a reviewer reference if one exists on somebody else's payment; preserve that payment. Normal customer roles cannot review payments through the app. |
| `users.professor_id` → `professors.id` | Remove the login account and its link. Preserve the separately managed Blue and Silver directory record; turn off the login-controlled student-delivery acceptance setting. |
| `orders.professor_id` → `professors.id` | Delete this customer's orders; preserve other customers' orders and their historical recipient snapshots. |
| `printing_shops.id` → `orders.shop_id`, `users.shop_id` | Preserve shops, staff assignments, services, prices, and fees. |
| `payment_settings` | Preserve the shared admin-managed payment instructions. |

The retained managed professor record can still contain a name, email, office, department, and Faculty. Other customers' existing orders may contain those professor recipient snapshots and payment records. They belong to the shop's directory or those other customers' orders, not to the deleted login account. The shop must manage separate requests to remove or correct that operational data. This deletion does not remove external backups or copies downloaded outside application-controlled private storage.

## Database and private-storage sequence

The service locks the authenticated user row where the database supports it, marks the account inactive within the transaction, and collects its order IDs and exact upload keys. The local storage backend validates each key and moves its file into a private staging directory on the same filesystem. It then deletes payment records, order items, orders, print configurations, upload metadata, and the user row in dependency order, all in one database transaction. A failed database or staging operation rolls back and moves staged files back to their original keys. Only after a successful commit are the staged files unlinked. No upload directory is deleted wholesale.

Database and filesystem writes cannot be one atomic transaction. A process crash or storage error immediately after database commit can leave unreferenced bytes in a private `.account-deletion-<random-id>` staging directory. The route reports an error and logs it rather than claiming full cleanup. With the application stopped, an operator runs:

```powershell
python -m flask --app wsgi:app recover-account-deletions
```

The command checks each staged key against live upload metadata, restores bytes still referenced by a rolled-back transaction, and deletes bytes whose records are gone. Run it only while deletion requests are stopped, so it cannot race with an active transaction. It reports restored and removed counts. The command operates on local private storage in development, testing, and production, including when production uploads are disabled. A different storage backend needs equivalent staging/recovery support before account deletion can remove its files.

No migration is required: existing foreign keys and columns support the explicit deletion order. The application stores sessions and remember credentials in signed browser cookies rather than a token table; removing the user prevents future authentication, while logout clears the current cookies.
