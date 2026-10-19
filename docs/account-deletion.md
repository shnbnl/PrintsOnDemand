# Account deletion

Students and professors can open **Account → Delete Account**, review the consequences, and submit their current password with explicit confirmation. The POST requires CSRF validation. The account ID comes from the authenticated session; submitted IDs cannot select another customer. Staff and administrators have no self-service account-deletion route.

Blue and Silver staff can separately delete a verified professor account through professor management after confirmation. This removes that professor's login, managed profile, owned orders, payment records, and private files. Ordinary profile approval changes do not delete historical orders.

## Data removed and preserved

| Data | Policy |
|---|---|
| Customer login | Delete the user and associated authentication sessions |
| Owned uploads | Delete metadata, print configurations, and exact private storage keys |
| Owned orders | Delete order items, fulfillment/recipient snapshots, and payment records |
| Linked professor profile | Remove the deleted professor account's managed profile |
| Other customers' orders | Preserve their records and recipient snapshots; clear references to the removed profile |
| Other customers' payments | Preserve payments; clear any reviewer reference to the deleted account |
| Shared shops and staff | Preserve shop records, services, rates, fees, assignments, and other accounts |
| Backups and downloaded copies | Not erased by this operation; follow the separate retention policy |

## Database and file sequence

The service locks the target account where supported, marks it inactive within the transaction, and collects owned order IDs and private file keys. Storage validates the keys and moves files into a private staging directory on the same filesystem. Payment records, order items, orders, configurations, and upload metadata are removed in dependency order. References from surviving records are cleared before deleting the account and applicable professor profile.

A database/staging failure rolls back and restores staged files where possible. After a successful database commit, staged bytes are purged. A postcommit purge failure is reported for operator attention; the deleted account cannot be restored merely by retrying the HTTP request. Successful self-deletion clears the browser session and remember cookie and requests browser cache/cookie/storage cleanup.

Database and filesystem changes cannot form a single atomic transaction. A hard interruption can leave files in private `.account-deletion-*` directories. With the app offline, run:

```bash
python -m flask --app run.py recover-account-deletions
```

Recovery restores staged files still referenced by database metadata and purges those whose records are gone. It must not race with active deletion requests. This is logical deletion from application-managed storage, not guaranteed forensic erasure from disks or external copies.

PostgreSQL account erasure uses an explicit authorized RLS scope for target history and surviving references. SQLite uses application ownership checks and explicit deletion order. See [Security operations](security-operations.md) for session revocation, database privileges, backup retention, and recovery requirements.
