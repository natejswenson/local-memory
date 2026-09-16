# Durable local recovery

## Lock ownership

Every engine operation, including reads, obtains `BEGIN EXCLUSIVE` on the fixed
`maintenance.sqlite3` inode before opening live state. SQLite/OS locks own the
lease, so a killed process releases it without PID guessing or stale-lock-file
removal. The lock file is never replaced or deleted. Operations serialize; this
trades concurrent reads for a simple cross-file maintenance boundary at the
bounded 10,000-record scale. Local fixed disks only. SQLite waits share a two-second budget and both public CLI supervisors kill a
worker at 4.8 seconds.
Adapters make at most one jittered BUSY retry within their 4.8-second call budget.

Each source adapter additionally holds its own SQLite mutex across source save,
state update and mirror attempt. Different owner adapters cannot write each
other's sources through the registry. SQLite WAL, FULL synchronization, foreign
keys, secure_delete, and the actual loaded SQLite version check apply to live
state. The separate deletion journal uses SQLite's rollback journal and FULL
synchronization; a committed intent survives a process kill without partially
parsed JSON lines. All directories/files are 0700/0600 with ownership and symlink
checks. Atomic metadata writes fsync the file, rename, then fsync the directory.

## Deletion

1. Under the maintenance lock, insert the unique ID and monotonic sequence into
   `deletions.sqlite3`. It contains only store identity and content-free
   `(sequence, id, complete)` entries, with no content/owner/source/recipients.
The committed journal ID itself is the permanent tombstone, outside live-store
capacity.

2. Commit deletion from live rows/FTS plus the content-free receipt and remove
   sharing selections. Startup replays all incomplete intents before reads.
3. Purge all managed backup and quarantine files; fsync those directories.
4. Commit `complete` in the deletion journal. Only then acknowledge logical
   deletion/managed-copy purge. If removal fails, `PURGE_PENDING` reports
   `active_deleted:true`, and no content reads proceed.
5. Checkpoint and VACUUM when possible. A held WAL reader leaves physical cleanup
   pending without restoring eligibility. Future maintenance retries compaction.

The journal is independent of snapshots and is never replaced by restore.
Missing/corrupt deletion state blocks operation. Tombstones and source adapter
ID/event associations prevent receipt replay/reconciliation from resurrecting
forgotten mirrors. Explicit new capture can create a fresh ID/event.

## Backup, corruption and restore

Snapshots use the SQLite online backup API, then integrity checks, size checks,
file fsync, and atomic publication of a manifest containing store ID, schema,
deletion sequence and SHA-256. Unpublished temporary snapshots are not restore
candidates. Corruption stops reads/writes. Under the maintenance lock, one
restricted copy of the corrupt database/sidecars is retained in quarantine where
possible; originals remain in place if preservation fails. No text salvage is
returned as memory.

Restore validates the manifest and snapshot against the **current** deletion
journal. It constructs a separate candidate, applies every current deleted ID,
clears all sharing, increments changed versions, removes receipts and selections,
and commits/checks integrity before publication. A durable restore-state file
binds the validated candidate's hash to recovery. Original database/sidecars move
to restricted quarantine, then the candidate is renamed into place and the
parent directory fsynced. Startup under the same lock resumes an interrupted
publication; it verifies the candidate hash and never serves a snapshot before
deletion replay and sharing reset. A crash before durable publication intent
leaves the prior live state. A crash after publication intent resumes the fully
prepared candidate. No live WAL file is copied as a backup or manually discarded.

Migrations require a validated pre-migration snapshot. Schema 1 currently accepts
only the defined v0 bootstrap layout as an upgrade input; arbitrary old table
layouts are not inferred. Unsupported old/new versions fail explicitly. A failed
migration rolls back its transaction and schema marker.

## Fault coverage

The public subprocess tests terminate workers at `before-commit`, `after-commit`,
`journal-durable`, `active-purged`, `copies-purged`, `journal-complete`,
`restore-copied`, `restore-reset`, `restore-quarantined`, and `restore-published`.
They inspect restarted public responses and persisted content/receipts/copies.
Source failure and mirror partial failure tests retain source authority. Real
unwritable backup permissions and a real held WAL reader exercise pending purge
and compaction. Synthetic failure points require **both** `NODE_ENV=test` and
`LOCAL_MEMORY_TESTING=1`; production host instructions never set either.

These are process-kill and filesystem-permission checks, not physical-power-loss
or failing-hardware certification. Durability assumes the storage stack honors
SQLite and fsync guarantees. Malicious same-user processes and OS rollback of the
entire directory are outside the threat model.
