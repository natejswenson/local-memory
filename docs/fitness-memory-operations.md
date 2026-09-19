# Fitness memory operations

The canonical preferences and coach journal are individual Markdown records under
`vault/Projects/local-fitness/{Preferences,Journal}`. The fitness application still
owns their semantics. Measurements, plans, settings, and generated reports remain
in the fitness repository and its operational database.

## Writer and clients

Run the hub environment's Python with `-m memory_hub.fitness_service --config
/path/to/private/control/config.json`. The installed launchd label is
`com.local-memory-hub.fitness`; it keeps one host process running. Configuration
includes the source repository, vault subtree, private control directory, token
file, backup directory, bind address, and port. The tested Docker Desktop setup
reaches **127.0.0.1:8766** through `host.docker.internal`; no LAN listener is needed.

Host clients use `LOCAL_FITNESS_MEMORY_URL=http://127.0.0.1:8766/memory`. The
container uses `http://host.docker.internal:8766/memory` and a read-only mount of
only the token file. It does not mount the vault or control directory. The token
is generated locally to authenticate this service; it is not an OpenAI API key.
No model/provider configuration changes are required.

`LOCAL_FITNESS_PREFERENCES_BACKEND` and `LOCAL_FITNESS_JOURNAL_BACKEND` independently
select `legacy` (default for other installations) or `vault`. Requested reads and
writes report unavailable memory on errors. Writes never silently fall back to
legacy storage. Optional preference prompt rendering may omit unavailable notes,
with a warning, following its established fail-open behavior.

Global `fitness` runs `fitness mcp-stdio`, exposing the full coach, Garmin data,
brief prompts, and the eight owner memory tools. It uses the same server key as
the project-local connection, avoiding duplicate tool aliases. The prior global
`fitness_memory --memory-only` setup was insufficient for fitness questions outside
the repository and has been replaced. Memory-only mode remains an optional app
feature, not this user's global registration. Existing sessions must restart to
load changed configuration. The shared `local-memory` skill distinguishes current
Garmin measurements from historical coach notes.
Generic Basic Memory indexing excludes `Projects/local-fitness` via the config
folder's `.bmignore`; generic writes to that subject/path are refused by the hub
wrapper. This prevents two application writers. It is not a sandbox against a
client that already has unrestricted filesystem access.

## Editing and failure behavior

Sequential Obsidian body edits appear on the next owner read. Keep filenames,
identity fields, and metadata intact. Preference bodies are one line; journal
bodies follow the existing 240-character limit. Invalid records stop the affected
operation and remain available for repair. Simultaneous human edits and application
writes are not an atomic collaboration protocol; finish one before starting the
other. Detected conflicts fail without discarding the human version.

The writer holds a lifetime host lock. Each mutation validates its resulting
records, persists a write-ahead transaction, then materializes Markdown and state.
Restart rolls a pending transaction forward. A conflicting external edit leaves
it pending for operator repair. Never delete `pending.json` to suppress an error.

Persistent request receipts make transport retries safe across restart. Correcting
or deleting a record retires content-bearing older receipts while retaining their
fingerprints, so an old request cannot recreate deleted data. A retry of a retired
request returns an error; use a fresh read. Deleted text can remain in historical
backups and migration snapshots until those are intentionally retired.

## Backup, restore, and rollback

Each successful application write and each hourly scan creates a checksum-verified
archive when record content or state changed. The writer retains the latest 14
archives in `control/backups/`. Archives include Markdown, record identity, journal
allocation floor, and retry state. Failed write-triggered backups are logged;
scheduled backup failures also create `control/backup-error`. Inspect writer logs
and that marker when checking health. The general hub daily vault backup is an
additional Markdown copy, not a substitute for a coordinated fitness archive.
These are local backups; machine/disk loss requires a separate external backup.

Restore to a **new quarantine path**, never over the active store:

```sh
.venv/bin/python scripts/fitness_migration/restore_store.py \
  --archive /path/to/fitness-backup.zip --destination /private/path/restore-check
```

Validate that restored store with `FitnessStore` using the installed fitness source.
Check row/text parity and next journal allocation before switching clients. Control
state and Markdown must be restored together. Restoration does not activate clients.

For rollback, stop and drain the writer and all clients first. Restore a coordinated
archive into quarantine, or use the stopped current store, then export:

```sh
.venv/bin/python scripts/fitness_migration/export_legacy.py \
  --vault /private/path/restored/vault --control /private/path/restored/control \
  --fitness-repo /path/to/local-fitness --destination /private/path/new-export
```

The export contains the two legacy preference files and a journal-only SQLite
artifact with its allocation floor. It never writes a live database. Apply only
those records to the current operational database in a reviewed SQLite transaction,
rebuild its journal FTS index, verify parity, and only then select legacy backends.
**Do not restore an old full fitness database**: that would roll back measurements
and unrelated state. Original configuration backups alone are not a data rollback
after new vault writes.

## Controlled installation

1. Land the tested adapter in the fitness repository's `dev` branch through its
   required feature/PR checks. Preserve existing provider settings.
2. Drain old fitness CLI/MCP processes and scheduled jobs, stop its container, and
   stop pre-upgrade generic hub processes. Do not interrupt unrelated agents/apps.
3. Create a new private `stage.py prepare` snapshot and verify it. Old rehearsal
   snapshots are not eligible for a live cutover.
4. `initialize_store.py` imports that frozen snapshot into **new** canonical/control
   directories, preserves deleted-row allocation history, generates the local token,
   and takes the first coordinated backup. Existing destinations are refused.
5. Preview then apply `scripts/install_fitness.py --repo ... --compose ... --control
   ... [--apply]`. It preserves unrelated settings, privately backs up originals,
   repairs invalid comments in scheduler XML without changing schedules, and writes
   the full fitness MCP registration and writer launchd file. It does not start anything.
6. Start the writer, verify preference and journal parity against the fresh snapshot,
   rebuild the fitness container from `dev`, and verify container health and memory
   access. Reload schedulers without forcing immediate email/calendar/model runs.
7. Verify fresh stdio clients and a fresh desktop chat. Record actual evidence in
   `fitness-migration-status.md`; global configuration alone is not desktop proof.

The hub wrapper waits for accepted generic writes to finish Markdown
materialization and background indexing before acknowledging them. This closes a
write/edit race seen during migration tests. The unchanged 16-check integration
probe now passes, including its five-second edit-refresh gate. This is measured
local behavior, not a hard real-time guarantee.
