# Persistent memory for the local skill family

Status: proposed design for [issue #2](https://github.com/natejswenson/local-memory/issues/2). Sources inspected 2026-09-15.
This issue delivers a document for review. No memory engine, integration, migration, or runtime behavior is shipped or tested here.

## Problem and goals

Useful preferences and corrections should survive a session and be available to another skill when the user selects that sharing.
The repository starts with an [empty tree](https://github.com/natejswenson/local-memory/commit/c7b2b5d86635d1389adb679d321e96c75e070815); existing skills have independent persistence contracts.
The proposed module provides small, attributable records with predictable scope, correction, retrieval, and deletion.

Goals:

- Remember reusable preferences, explicit corrections, user-confirmed facts, and bounded project context across process restarts.
- Return relevant context within a fixed budget; explain where it came from and whether it needs review.
- Make private storage the default and sharing a deliberate choice of eligible skills.
- Preserve existing source stores and action-authorization contracts through incremental adoption.
- Give users visible inspection, correction, export, and deletion controls.

Non-goals: source-document storage, transcript archives, credentials, configuration management, operational receipts, action approvals, cloud synchronization, hosted services, multi-user isolation, or changes to branching/CI/release policy in issue #1.

## Survey and initial consumers

These are observations of public **SKILL.md contracts**, not audits of script internals or live personal stores. Paths in those sources describe the contracts; this document contains no private store contents.

| Inspected contract | Persistence and authority observed | Consequence for this design |
|---|---|---|
| **ghostwriter 0.23.1**, revision `5bcc19d6b341b375d58e6429ed17ef5872c4b381` | [Personal voice data is separate from installation files](https://github.com/natejswenson/claude-skills/blob/5bcc19d6b341b375d58e6429ed17ef5872c4b381/skills/ghostwriter/skills/ghostwriter/SKILL.md#L47); [direct feedback takes priority](https://github.com/natejswenson/claude-skills/blob/5bcc19d6b341b375d58e6429ed17ef5872c4b381/skills/ghostwriter/skills/ghostwriter/SKILL.md#L403); [style feedback must be saved before redrafting](https://github.com/natejswenson/claude-skills/blob/5bcc19d6b341b375d58e6429ed17ef5872c4b381/skills/ghostwriter/skills/ghostwriter/SKILL.md#L520). | First opt-in consumer: recall selected preferences and corrections. Keep voice sources, credentials, and publishing responsibilities separate. |
| **resume 2.0.0**, revision `1fe3597b471413ab1fb900e86064891b85289bf0` | [Stored résumé management](https://github.com/natejswenson/claude-skills/blob/1fe3597b471413ab1fb900e86064891b85289bf0/skills/resume/skills/resume/SKILL.md#L240) specifies installation-independent source text, controlled replacement, backup, inspection, and deletion that leaves the prior backup. | The résumé remains a source document. Do not copy career facts into shared memory or alter its backup contract through this module. |
| **gmailtriage 0.8.1**, revision `e5a8d93a408d57dfa14295c90fe43579cc304a22` | [Validated rules have backups](https://github.com/natejswenson/claude-skills/blob/e5a8d93a408d57dfa14295c90fe43579cc304a22/skills/gmailtriage/skills/gmailtriage/SKILL.md#L59); [durable receipts support undo](https://github.com/natejswenson/claude-skills/blob/e5a8d93a408d57dfa14295c90fe43579cc304a22/skills/gmailtriage/skills/gmailtriage/SKILL.md#L395); [mail actions require user rules](https://github.com/natejswenson/claude-skills/blob/e5a8d93a408d57dfa14295c90fe43579cc304a22/skills/gmailtriage/skills/gmailtriage/SKILL.md#L479). | Rules and receipts stay in their authoritative stores. A remembered preference cannot file, archive, or delete mail. |

Synthetic use cases: retain “avoid hashtags” for later writing; correct it to “at most one relevant hashtag”; remember a confirmed public project acronym; recall a project's intended audience across writing sessions.
Only the first case is proposed for the initial integration. A later adapter could share a writing preference with an explicitly selected writing skill.
The other cases define the model's boundaries and potential follow-up consumers, not existing integrations.

## Version-one boundaries

One local OS user, one database, short text records, foreground calls, explicit keys, and a small registered set of adapters.
Assume at most **10,000 live records and 100 MiB of database plus indexes**; these are design limits to validate, not measured demand.
Cap record text at 2 KiB UTF-8, all record metadata at 2 KiB, request JSON at 16 KiB, and recalled context at 8 KiB including metadata, with at most 10 records.
Reject requests above limits; never silently truncate a stored fact. At capacity, reads and deletion work, while new capture returns `CAPACITY` until cleanup.
Backups have a separate bounded allowance: three snapshots, each at most 100 MiB. WAL growth is monitored separately below.

No embeddings, vector service, background inference, automatic transcript ingestion, always-on MCP server, or arbitrary SQL interface.
No runtime may invent persistent memory when local process execution or the selected data directory is unavailable.
Skills may continue their ordinary task without optional memory, while explicitly reporting a failed requested save.

## Alternatives and recommendation

| Approach | Strengths | Costs and limitations | Decision |
|---|---|---|---|
| Markdown or JSON files | Easy manual reading, simple distribution and export | Requires custom locking, indexes, atomic multi-record updates, version conflicts, and backup deletion | Keep as inspection/export formats |
| SQLite metadata plus lexical retrieval | Transactions, indexed scope filters, stable IDs, bounded local queries; optional FTS5 | Runtime binding and migration support must be selected; one writer at a time | **Recommend** |
| Embedded vector store | Can find paraphrases without shared vocabulary | Embedding generation, model/version changes, dependencies, relevance evaluation, and more sensitive derived data | Defer until pilot shows lexical misses worth the cost |

Recommend a runtime-neutral **JSON CLI**, tentatively `local-memory request`, reading one JSON object from stdin and returning one JSON object on stdout.
It avoids a daemon and can serve multiple agent hosts without embedding database code in each skill. A language library would couple callers to a runtime; MCP adds service lifecycle and a wider surface before need is measured.
Adapters invoke a fixed executable with an argument array; memory content never enters shell command text.

Use structured equality filters first and FTS5 for optional lexical search. SQLite documents [FTS5 queries and tokenizers](https://sqlite.org/fts5.html); installation must probe availability.
If unavailable, scan the bounded eligible set using normalized literal tokens and disclose `retrieval_mode: "scan"`. Do not install dependencies or change sharing policy during recall.
Exact-key recall is the pilot's primary path and must work identically with either retrieval mode. Free-text ranking may differ and is measured separately.

Candidate packaging is a Node CLI using a supported SQLite binding. The inspected [Node SQLite documentation](https://nodejs.org/api/sqlite.html) provides `DatabaseSync` and backup support, but labels the module a release candidate.
This is evidence of an API option, not a supported-runtime promise. Packaging, runtime minimums, bundled SQLite, and sandbox smoke tests are a blocking compatibility spike before implementation.

```text
current user instruction -> host adapter -> JSON CLI -> scope filter -> SQLite
                                ^              |
                                +-- bounded untrusted records --+
existing skill source stores <-> adapter (pilot precedence and reconciliation)
```

## Memory model and lifecycle

Records hold one proposition, not an entire profile. `type` is `preference`, `fact`, or `project_context`; a correction is an update with explicit provenance, not a separate competing type.

| Field | Meaning and constraints |
|---|---|
| `id` | Engine-issued UUID; stable across updates, never reused after forget |
| `key`, `type`, `content` | Registered dotted ASCII key, one allowed type, bounded UTF-8 text |
| `user_id` | Random local namespace set at initialization; injected by adapter, not accepted from record content |
| `project_id` | Registered opaque project ID or `null` for user-wide applicability |
| `owner_skill` | Registered creating skill; immutable; selected recipient skills can read but cannot silently edit |
| `share_with` | Explicit skill-ID allowlist; empty by default; no wildcard or transitive sharing |
| `provenance` | `kind`: `explicit_user`, `explicit_correction`, `confirmed_fact`, or `inferred`; skill/version, opaque source reference, and source observation time |
| `created_at`, `updated_at` | Engine UTC timestamps; update time is not evidence that a fact is still true |
| `review_after`, `expires_at` | Review and expiry deadlines, or `null` where permitted; reads never renew them |
| `version`, `status` | Positive integer optimistic-lock version; `active`, `suggested`, or `conflicted` |
| `dedupe_key` | Engine encoding of exact tuple `(user_id, project_id-or-sentinel, owner_skill, type, key)`; unique among live records |

Supporting tables hold scope registrations, sharing selections, schema metadata, deletion IDs, and bounded content-free mutation receipts.
The source reference is a logical marker, not a transcript, credential, raw URL query, absolute path, or instruction to fetch a file.
Do not store old content versions in v1. Version counters and mutation metadata support concurrency without making a hidden conversation archive.

Lifecycle rules:

1. `remember` creates version 1 after validation and capture-policy checks. Engine assigns identity, dedupe key, timestamps, and defaults.
2. Same dedupe tuple and identical canonical content/metadata returns the existing ID/version (`deduplicated: true`). Canonicalization normalizes line endings and Unicode NFC, trims outer whitespace, and sorts sharing IDs; it does not paraphrase.
3. Same tuple with different content returns `DUPLICATE_CONFLICT`, preserving the existing record. Use explicit `update` with its expected version to resolve it. An old inferred input cannot overwrite a correction.
4. `update` increments version and replaces selected mutable fields atomically. ID, owner, user, project, key, and type are immutable; moving scope requires a reviewed new record and separate forget. Reject inferred updates to confirmed/explicit records; a changed explicit value requires a current user correction validated by the adapter.
5. No automatic last-writer-wins merge: stale `expected_version` returns `VERSION_CONFLICT`. Two explicit corrections require rereading and applying the user's intended correction, not retrying an overwrite blindly.
6. Inferred proposals, if supplied for user review, are private `suggested` records, expire after seven days, and never appear in normal recall. Confirmation changes provenance and status through versioned update.
7. Preferences default to review after 180 days with no automatic expiry. Confirmed facts/project context default to review after 30 days and expire after 90; users may shorten deadlines or explicitly renew them. Facts and project context cannot have indefinite expiry in v1.
8. At `review_after`, normal recall excludes a record; inspection shows it as stale. At `expires_at`, all normal recall excludes it immediately, even if cleanup has not run. Foreground maintenance purges expired records through the forget protocol; no background process is implied.
9. Forget removes live content and derived indexes, records only the deleted ID and deletion sequence, and schedules physical cleanup. Its backup semantics are specified below.

For multiple eligible owners with the same type/key, compare provenance and project applicability before ranking.
Explicit corrections outrank explicit preferences/confirmed facts; inferred suggestions never compete. Among equal provenance, a matching project record overrides a user-wide record.
Equal-precedence differing values become a retrieval conflict: withhold that key and return `conflict_keys`, without choosing by arrival time or owner name.
Equal values can collapse to one result with bounded source IDs. A user resolves ambiguity by correcting or forgetting the conflicting records through the management interface.
Different keys may express contradictory ideas; v1 has no semantic conflict detection. Adapters use registered keys and show uncertain conflicts for review. A user may mark an uncertain record `conflicted` through versioned update; only explicit resolution back to `active` makes it eligible again.

## Scope and retrieval

Scope is conjunctive: same user **and** matching project (or user-wide) **and** owner/allowlisted skill **and** active, unexpired, reviewed status.
A project record never becomes user-wide merely because it is shared. A projectless session gets only user-wide records; an unknown project ID is rejected.
Filter before ranking, snippet construction, conflict metadata, and counting. An ineligible caller receives no hint that another record exists.

Adapter setup registers a skill ID and user-selected canonical project roots in per-user configuration outside repositories.
The host adapter resolves the current working directory against those registered roots and injects identity. A project label or a repository file supplied by the model is not authorization.
New clones/worktrees must be explicitly associated with a project; display-name equality or a remote URL never grants access.
Sharing changes require a current user selection bound to the record/version and recipients by the adapter. `share_with` in model-authored JSON alone is insufficient.
Owner adapters may update their records; a separate interactive management entrypoint can inspect/edit/delete any record for the local user. Recipient adapters request corrections instead of changing owners' data.
These checks prevent accidental cross-project disclosure by cooperative adapters; they are not a security sandbox against malicious code running as the same OS user.

Recall accepts exact `keys` or free-text `query`, plus optional type filters. Empty keys/query is invalid; listing all records is an inspection operation.
For free text, use up to 16 literal tokens from at most 256 characters, with query operators escaped. Match exact key or all requested tokens in key/content; bind SQL parameters.
FTS5 mode uses a documented tokenizer; scan mode uses NFC, lowercase, and Unicode letter/number tokens with no stemming. Responses disclose the mode so quality comparisons remain honest.
After resolving same-key conflicts and precedence, rank exact-key matches first, then lexical score, then `updated_at` descending, then ID ascending for a stable tie break.
Freshness is eligibility, not permission to discard a correction in favor of a newer inference.
Default recall is five records/4 KiB; hard maximum is ten/8 KiB of serialized `context` UTF-8, including provenance and conflict keys.
Drop whole lowest-ranked records to fit; report `truncated` and `omitted_count` for eligible results only. Never cut a sentence into a different meaning.
Adapters must also respect the host's remaining context budget and may request less. No token count is promised across models.

## Interface and worked examples

Protocol version 1; proposed command names below are specifications, not installed commands.
All requests carry `protocol`, `op`, `request_id`, and adapter-injected `caller`. Mutations carry an idempotency key; examples use synthetic identifiers and text throughout.
Transport is bounded stdin/stdout JSON; stderr contains redacted diagnostics, never record bodies. Exit 0 means an `ok: true` response, 2 invalid input, 3 unavailable/storage failure, 4 conflict/policy refusal.

### 1. A selected preference is written

The user asks to remember this for Project Harbor and selects `writing-peer` as another eligible skill. That name is a hypothetical protocol client, not a surveyed or shipping integration.
The adapter has already validated that selection and registered both caller and project. This standalone protocol trace uses an independent memory record, not a source-backed pilot mirror; the initial pilot remains private as described below.

```json
{
  "protocol": 1, "op": "remember", "request_id": "req-001", "idempotency_key": "capture-001",
  "caller": {"skill_id": "ghostwriter", "project_id": "prj-harbor"},
  "record": {
    "type": "preference", "key": "writing.hashtags", "content": "Avoid hashtags in Project Harbor posts.",
    "share_with": ["writing-peer"],
    "provenance": {"kind": "explicit_user", "skill_version": "0.23.1", "source_ref": "user-event-001", "observed_at": "2026-09-15T10:00:00Z"}
  }
}
```

```json
{"ok":true,"request_id":"req-001","id":"8bb391e4-522b-482e-b893-949acb905001","version":1,"deduplicated":false}
```

Inspection returns the full example record (the dedupe tuple is encoded as a JSON-array string without delimiter ambiguity):

```json
{
  "id": "8bb391e4-522b-482e-b893-949acb905001", "type": "preference", "key": "writing.hashtags",
  "content": "Avoid hashtags in Project Harbor posts.", "user_id": "usr-example", "project_id": "prj-harbor",
  "owner_skill": "ghostwriter", "share_with": ["writing-peer"],
  "provenance": {"kind": "explicit_user", "skill_version": "0.23.1", "source_ref": "user-event-001", "observed_at": "2026-09-15T10:00:00Z"},
  "created_at": "2026-09-15T10:00:00Z", "updated_at": "2026-09-15T10:00:00Z",
  "review_after": "2027-03-14T10:00:00Z", "expires_at": null, "version": 1, "status": "active",
  "dedupe_key": "[\"usr-example\",\"prj-harbor\",\"ghostwriter\",\"preference\",\"writing.hashtags\"]"
}
```

### 2. A later session recalls it after restart

```json
{"protocol":1,"op":"recall","request_id":"req-002","caller":{"skill_id":"ghostwriter","project_id":"prj-harbor"},"keys":["writing.hashtags"],"limit":5,"max_context_bytes":4096}
```

```json
{
  "ok": true, "request_id": "req-002", "storage": "ready", "retrieval_mode": "exact",
  "context": {"records": [{"id":"8bb391e4-522b-482e-b893-949acb905001","version":1,"key":"writing.hashtags","content":"Avoid hashtags in Project Harbor posts.","project_id":"prj-harbor","owner_skill":"ghostwriter","provenance":{"kind":"explicit_user","source_ref":"user-event-001"},"review_after":"2027-03-14T10:00:00Z","untrusted":true}],"conflict_keys":[]},
  "truncated": false, "omitted_count": 0
}
```

### 3. Selected sharing and isolation

```json
{"protocol":1,"op":"recall","request_id":"req-003","caller":{"skill_id":"writing-peer","project_id":"prj-harbor"},"keys":["writing.hashtags"]}
```

This returns the same version-1 context as `req-002`, with `request_id: "req-003"`; the recipient gains no write privilege.
A registered but unlisted skill in Harbor, or `writing-peer` in registered `prj-orbit`, receives the following response to its request `req-004`:

```json
{"ok":true,"request_id":"req-004","storage":"ready","retrieval_mode":"exact","context":{"records":[],"conflict_keys":[]},"truncated":false,"omitted_count":0}
```

Unknown callers/projects instead receive `SCOPE_INVALID`. For lexical search, substitute `"query":"hashtags"` for `keys`; eligibility is unchanged.

### 4. A correction replaces the preference

Current instruction: “Actually, use at most one relevant hashtag.” The owner validates the current user correction and submits:

```json
{
  "protocol": 1, "op": "update", "request_id": "req-005", "idempotency_key": "correction-001",
  "caller": {"skill_id":"ghostwriter","project_id":"prj-harbor"},
  "id": "8bb391e4-522b-482e-b893-949acb905001", "expected_version": 1,
  "patch": {"content":"Use at most one relevant hashtag in Project Harbor posts.","provenance":{"kind":"explicit_correction","skill_version":"0.23.1","source_ref":"user-event-002","observed_at":"2026-09-16T10:00:00Z"},"review_after":"2027-03-15T10:00:00Z"}
}
```

```json
{"ok":true,"request_id":"req-005","id":"8bb391e4-522b-482e-b893-949acb905001","version":2}
```

Later eligible recall returns version 2 and the corrected text; version 1 is absent from active rows and indexes.
A concurrent update based on version 1 fails without modifying version 2:

```json
{"ok":false,"request_id":"req-006","error":{"code":"VERSION_CONFLICT","retryable":false,"current_version":2}}
```

### 5. The user forgets it

The user selects the displayed ID. The owner adapter or user-management entrypoint may delete it; a read-only recipient may not.

```json
{"protocol":1,"op":"forget","request_id":"req-007","idempotency_key":"forget-001","caller":{"skill_id":"ghostwriter","project_id":"prj-harbor"},"id":"8bb391e4-522b-482e-b893-949acb905001","expected_version":2}
```

```json
{"ok":true,"request_id":"req-007","id":"8bb391e4-522b-482e-b893-949acb905001","deleted":true,"managed_backups":"purged","physical_cleanup":"pending"}
```

This success is returned only after the managed-backup purge completes. All subsequent eligible recall is empty, including after supported restoration; cleanup status concerns physical remnants, not recall eligibility.
Deleting an already deleted ID with a valid caller is idempotent. Unknown/inaccessible IDs return the same `NOT_FOUND` on inspection/update, without revealing other scopes.

### Missing data, errors, and retries

A never-initialized store returns successful empty recall with `storage: "absent"`; recall must not create directories. If initialization metadata exists but the database disappears, return `STORAGE_MISSING`, not an empty fresh store.
Initialization is an explicit setup operation; writes before setup return `NOT_INITIALIZED`. An inaccessible path, disk-full error, or unsupported host returns an unavailable error, for example:

```json
{"ok":false,"request_id":"req-008","error":{"code":"STORAGE_UNAVAILABLE","retryable":false,"message":"Memory storage is not accessible; no save was confirmed."}}
```

Other codes: `INVALID_INPUT` (bad JSON/schema/limits/unknown fields), `PERMISSION_DENIED`, `SECRET_REJECTED`, `CAPACITY`, `BUSY`, `CORRUPT`, `SCHEMA_TOO_NEW`, `MIGRATION_REQUIRED`, and `PURGE_PENDING`.
Return safe field names, not rejected content. `NOT_FOUND` differs from an empty search; `VERSION_CONFLICT` is an actionable concurrency result, not success.
Per-call lock waiting is capped at two seconds. An adapter may retry `BUSY` once with jitter and the same idempotency key, within a five-second overall foreground deadline; otherwise continue without optional memory.
For lost responses, replay the same mutation key before assuming failure or success. Receipts retain a keyed digest of the canonical operation payload (excluding transport `request_id`) and result IDs/versions for 30 days, never content; same key/different payload returns `IDEMPOTENCY_CONFLICT`.
Receipts and mutation commit together. Replay still checks current scope and deletion status; a forgotten target returns `GONE`, never a fresh save acknowledgment. After 30 days automatic replay is unsupported: inspect state before a new mutation. Delete tombstones outlive receipt expiry and block resurrection of the same ID.
No error permits reporting “remembered.” A partially completed forget reports `PURGE_PENDING` with `active_deleted: true` and can be resumed using the same key.

## Persistence and recovery

### Location, initialization, and upgrades

Use one directory independent of skill installation: macOS `~/Library/Application Support/local-memory/`, Linux `${XDG_DATA_HOME:-~/.local/share}/local-memory/`, or Windows `%LOCALAPPDATA%\local-memory\`.
A user-configured absolute `LOCAL_MEMORY_HOME` override takes precedence; never derive it from a repository or recalled value. All adapters must resolve the same configured location and report it through `status`.
Inside: `memory.sqlite3`, SQLite sidecars, initialization/schema metadata, content-free deletion journal, and module-managed `backups/` and `quarantine/` directories.
Local fixed-disk filesystems only; reject known network/synchronized locations and document that filesystem detection is imperfect. Override changes require explicit relocation, not silent creation of a second store.
Use owner-only directory/file permissions (0700/0600 on POSIX; equivalent user ACLs on Windows), reject unsafe ownership and symlink substitution, and redact data from logs. This is not encrypted storage.
No skill updater owns this directory. Upgrading/removing a skill leaves memory intact; deleting module data is a separate user operation.

### Transactions, concurrent access, and interrupted writes

Use SQLite WAL, `synchronous=FULL`, foreign keys, a two-second busy timeout, and short transactions for record/index/version/receipt changes.
Readers get a committed snapshot; writers serialize. SQLite's [WAL documentation](https://sqlite.org/wal.html) explains the single-writer and local-host constraints and notes that WAL sidecars are part of persistent state.
Require SQLite 3.51.3 or later, or an explicitly verified fixed backport, because that documentation identifies a WAL-reset corruption fix affecting concurrent connections. The packaging spike must verify the actual linked version.
On normal restart, open the existing database and let SQLite recover committed state; never rebuild an empty store because opening failed.
Interrupting a transaction yields either the old or committed state; the receipt disambiguates a lost acknowledgment. Atomicity depends on the storage stack honoring required I/O guarantees, as documented in [SQLite atomic commit](https://sqlite.org/atomiccommit.html).
Do not manually copy/delete a live WAL. Checkpoint opportunistically after short reads end; cap a recall transaction at the foreground deadline.
At WAL size above 32 MiB, attempt a checkpoint and report maintenance pressure. At 64 MiB, refuse additional captures with `CAPACITY` until readers release/maintenance succeeds; allow deletion and recovery operations.
These are admission thresholds, not a hard filesystem-size guarantee: one transaction and delayed checkpoints can exceed them. Physical cleanup may wait for other readers.

### Corruption, schema migration, and backups

An integrity/open failure stops reads and writes with `CORRUPT`. Under an exclusive maintenance lock, preserve database plus sidecars in restricted quarantine; do not return salvaged text as trustworthy memory.
If quarantine cannot be created, preserve originals in place and stop. A user-triggered recovery verifies a snapshot, schema, and current deletion journal before atomically installing a restored database and rebuilding indexes.
Never silently restore, overwrite originals, or treat missing/corrupt deletion metadata as empty. If no valid snapshot exists, offer inspectable export/salvage in a later recovery tool or an explicit reset that acknowledges data loss.
Store an integer database schema version separately from protocol and record versions. Ordinary calls refuse newer schemas and return `MIGRATION_REQUIRED` for older ones.
An explicit migration obtains the maintenance lock, makes a validated snapshot, applies a transactional migration, checks integrity, then advances the schema version. Failure preserves the old supported state; never run a downgrade automatically.
Use SQLite's [online backup API](https://sqlite.org/backup.html) to produce consistent snapshots, then validate and atomically publish a manifest. Plain copying an open database file is unsupported.
Backups are opt-in: at most one per day before the first mutation, plus mandatory pre-migration snapshots, with three total retained and maximum age 30 days. Initialization records the choice.
Backup maintenance runs in foreground; a requested backup failure is visible and a failed mandatory pre-migration backup prevents migration. No snapshot is published without integrity and deletion-sequence metadata.

### Forget, retention, and restoration

Logical deletion immediately excludes a record from every normal and management content read. Physical deletion means removing live rows, FTS entries, old content remnants during compaction, and module-managed copies; it does not promise forensic erasure of SSD blocks.
Forget and expiry cleanup use a resumable protocol under a maintenance lock respected by every module process:

1. Durably append an intent with sequence and record ID only to a separate deletion journal before removing content. Startup replays pending intents before serving any read.
2. Delete live content/index rows and record the content-free tombstone in a transaction. Mutation receipts never contain old text.
3. Remove all module-managed snapshots and quarantine copies that could contain the ID; v1 may purge all such copies to avoid uncertain indexing. Block snapshot publication throughout this protocol.
4. Mark the journal intent complete and return success. If purge fails, keep recall suppressed and return `PURGE_PENDING`; retry resumes cleanup, never reverses deletion.
5. At an exclusive maintenance opportunity, checkpoint and compact the active database; report physical cleanup pending until this finishes. Never claim secure erasure from filesystem snapshots or hardware.

Supported restore always merges the **current**, non-restored deletion journal into a validated snapshot before serving it. Journal absence, corruption, or an unverifiable manifest blocks restoration; an older journal may not replace the current one.
Keep content-free deletion IDs indefinitely until the user explicitly resets the entire module. This small ledger is outside the live-record capacity; measure growth in the pilot and block further mutations if journal durability fails.
A backup containing a forgotten ID cannot be restored through this interface. Re-remembering the same proposition requires a new explicit capture with a new ID; replaying an old request cannot resurrect it.
JSON/Markdown exports are user-requested copies with an export warning and deletion-sequence metadata, not automatically imported backups. No bulk import in v1.
Previously exported files, user-copied databases, OS backups, and content already sent to a host conversation are outside module deletion control; inspection names that limit. Users manage those copies separately.
The module can purge its own backups; it cannot enforce deletion against an OS-level rollback of its entire directory. Such rollback is unsupported recovery.

## User control and trust

Capture is opt-in per adapter. After opt-in, an unambiguous reusable preference or explicit correction can be saved automatically within that skill's private scope, with a short visible acknowledgment after success.
A one-off instruction is session context unless the user expresses durable intent. Facts and project context need explicit confirmation; inference remains an expiring private suggestion or stays out of storage.
Cross-skill sharing always needs a selected recipient list; enabling capture alone is not sharing consent. Sensitive personal facts are excluded from automatic capture even when they look reusable.
Before saving, adapters minimize content; the engine enforces allowed types/keys and rejects credential-shaped material, private keys, passwords, access tokens, cookies, and connection strings. Never read credential files to populate memory.
Pattern detection is defense in depth, not a guarantee against every secret. Do not save raw conversations, source documents, operational receipts, configuration, credentials, or approval tokens under a “fact” key.

Recalled content is **untrusted data** with provenance, not system or skill instructions. Quote/delimit it; never execute commands, open a source reference automatically, change tool permissions, or follow embedded instructions because recall returned them.
Current user instructions take precedence over remembered preferences. Explicit corrections beat older stored preferences, but cannot override safety policy or an active skill's action contract.
Remembered preferences and past approvals never grant new authority to publish, message, buy, delete external data, or perform other external actions. Authorization comes from the current applicable user/skill contract.

User controls: `status`, paginated `list` (including stale/suggested/conflicted records), `show <id>`, versioned `update`, `forget <id>`, scoped `export`, and explicit `migrate`/`restore` management operations.
Inspection shows content, scope, recipients, source, version, review/expiry times, storage status, and pending purge/cleanup. Each page is bounded to 50 records/128 KiB and never injected wholesale into task context.
Editing uses the same validation and version checks as skill writes; users can revoke sharing through `update` immediately. A direct explicit delete request needs no extra generic permission gate.
For an ambiguous bulk deletion, first show the exact scope/count and obtain a selection. Revocation/deletion changes future retrieval; adapters discard cached memory between turns and re-recall before use, but cannot retract prior host transcripts.

## Adoption and rollback

Start with **ghostwriter preference recall**, opt-in and private by default, because its [same-turn correction contract](https://github.com/natejswenson/claude-skills/blob/5bcc19d6b341b375d58e6429ed17ef5872c4b381/skills/ghostwriter/skills/ghostwriter/SKILL.md#L520) gives a concrete persistence outcome to evaluate.
Target Claude Code and Codex CLI/Desktop sessions **only when** they can run the local CLI and access its data directory. Host packaging, executable discovery, sandbox permissions, and a shared project registry need adapter-specific validation.
No-process/no-filesystem hosts return unavailable. Do not assume a plugin install exposes another host's data directory or installs a compatible Node version.

Pilot precedence: current user instruction, then existing voice notes, then a validated matching memory mirror, then broader profile/default guidance. A memory mirror cannot silently override changed source notes.
Keep source documents and source-store writes intact. Do not backfill whole voice profiles; select one preference key at a time with the user's opt-in. No live migration belongs to this issue.
For a new correction: save the existing voice-note correction first, verify it, then mirror it with a stable source-event marker and source revision digest held in adapter metadata.
If the source save fails, do not create a memory-only correction; follow the existing skill's failure behavior and report persistence failure. If mirroring fails, the saved source correction remains authoritative and the adapter reports memory sync pending.
Before recall use, compare source revision metadata. A changed/unreadable source invalidates its mirrors until the adapter reconciles selected keys; never let stale mirrors win. Reconciliation must check deletion tombstones and must not recreate forgotten mirrors automatically.
No atomic transaction spans both stores. Source-first ordering, idempotent mirroring, visible pending state, and exclusion of mismatched mirrors are the contract for partial writes.
During this pilot, mirrored records remain private. The worked sharing example exercises the future standalone protocol; sharing source-backed mirrors waits for a validated reconciliation strategy that protects recipients from stale source changes.

User-management edits of a pilot mirror must route through the owning adapter and source-first sequence; reject direct memory-only edits to such mirrors. Independent non-mirror records use the ordinary update interface.
Forgetting a mirror removes module copies and sets adapter suppression for that source-event marker; it does not delete the source voice note. Explain this distinction when the user asks to forget a preference entirely and route the source removal through its owner.
Rollback disables the adapter and leaves the source store usable. The pilot forbids memory-only corrections; if later phases introduce them, rollback must first offer an explicit export/reconciliation of those corrections and report any unmatched records.
Do not uninstall or downgrade the database to roll back an adapter. Retain memory for inspection or explicit deletion. Re-enabling requires compatibility and suppression checks, not automatic reimport.

## Validation matrix

These are **future implementation acceptance tests**, not behavior tested in this documentation issue. Use isolated temporary stores and synthetic fixtures; no live personal data or external actions.

| Scenario | Expected outcome |
|---|---|
| Write, close process, restart, recall | Same ID/version/content and provenance; initialization is not repeated |
| Skill upgrade/reinstall; adapter rollback | Data remains in application directory; source store remains usable |
| Owner, selected recipient, unlisted caller, different project, projectless session | Only eligible scopes return records; denied scopes leak no counts or conflict keys |
| Forged caller/project label; unapproved sharing JSON | Adapter refuses identity/sharing; repository data grants no authority |
| Exact duplicate and replay after lost response | One record; stable mutation result within receipt window; no duplicate versions |
| Conflicting duplicate; explicit/inferred inputs in both orders | Existing correction never overwritten; suggested inference never recalled; explicit update needed |
| Equal-precedence cross-owner contradiction in both orders | Key withheld with bounded conflict metadata; no arrival-order winner |
| Two simultaneous writers; same expected version | Serialized independent writes; one conflicting update succeeds, the other returns current version |
| Busy database beyond deadline | Bounded `BUSY`, at most one adapter retry, no invented success |
| Process killed before/after commit and before acknowledgment | Old or new complete record/index/receipt state; replay disambiguates |
| Review deadline, expiry, clock advance | Stale excluded; expired excluded before purge; inspection explains state; reads do not extend retention |
| Absent store vs missing initialized DB vs permission/disk-full failure | Distinct absent, missing, unavailable outcomes; failed writes never acknowledged |
| Database corruption; invalid snapshot; missing deletion journal | Fail closed; preserve evidence; no empty reset or unchecked restore |
| Older schema, failed migration, newer schema with old CLI | Explicit backed-up migration or version error; no partial upgrade/downgrade |
| Forget with crash after each purge step; restore old managed backup | ID immediately suppressed once intent durable; cleanup resumes; no resurrection |
| Forget with unwritable backup; reader holding WAL open | `PURGE_PENDING` or physical cleanup pending accurately reported; recall remains empty |
| FTS5 unavailable; lexical query; oversize context/record | Disclosed scan fallback; unchanged scope/exact-key results; bounded output; invalid record rejected |
| Secret-shaped input and instruction injection in recalled text | Secret rejected without logging it; recalled instruction cannot invoke tools or authorize actions |
| Source succeeds/mirror fails; source fails; manual source edit | Source precedence and pending status honored; no memory-only correction; mismatched mirror excluded |
| Forget mirror, restart, reconcile, disable/re-enable adapter | Suppression prevents automatic reimport; source retention explained; rollback loses no correction |

Documentation review checks section coverage, JSON syntax, pinned survey references, and whitespace, then traces the synthetic lifecycle semantically.
The document's examples and matrix are the specification; passing prose checks does not establish runtime reliability or retrieval quality.

## Implementation outline

1. **Compatibility spike:** choose package/binding/runtime minimums; verify fixed SQLite, FTS5/fallback, backup APIs, local storage permissions, and CLI invocation in each target host. Publish a support matrix and fixtures; no live data.
2. **Core local module:** schema, initialization/identity registry, validated JSON operations, deterministic scope/retrieval, version conflicts, limits, and content-free idempotency receipts. Implement lifecycle tests from the matrix.
3. **Recovery and user management:** deletion journal/managed-backup purge, maintenance locking, corruption handling, migrations, export/inspection, secret filtering, and fault-injection tests. Do not enable capture before forget/restore invariants pass.
4. **Private ghostwriter pilot:** adapter opt-in, one or a few registered preference keys, source-first mirrors, revision validation, suppression, unavailable behavior, and rollback. Measure repeated-correction avoidance and exact-key recall in synthetic sessions, then an optional user-selected pilot.
5. **Selected sharing and broader records:** resolve source-mirror recipient freshness, test eligible second adapter and project isolation, then expose explicit sharing. Measure lexical misses before reconsidering embeddings or new consumers.

Each phase should become bounded implementation issues with the relevant matrix rows and dependencies. This issue closes through document review; none of these phases is implied to have shipped.

## Decision log

Settled recommendations for review: local SQLite plus optional FTS5 and bounded scan fallback; one JSON CLI; installation-independent per-user data; private defaults and explicit recipient selection; explicit corrections with version checks; source-first private ghostwriter pilot; no secrets or action authority; deletion-aware restoration; no engine in this issue.

| Open question / risk | Impact | Proposed resolution | Blocks implementation? |
|---|---|---|---|
| Package, SQLite binding, supported host/runtime versions | Could add dependencies or make WAL/backup/FTS features unavailable | Phase 1 compatibility spike on each host; verify linked SQLite fix and binding stability | **Yes: core implementation/package selection** |
| Portable maintenance lock and deletion-journal durability | Cross-file crash recovery or concurrent restore could resurrect deleted data if incorrect | Specify lock ownership, fsync/atomic replacement, replay, and kill-point tests before phase 3 | **Yes: recovery implementation and all capture rollout** |
| Source-backed sharing freshness | Another skill cannot independently know a mirror's source changed | Keep pilot private; design validated source-revision checks or adapter reconciliation before sharing mirrors | **Yes: sharing source-backed mirrors only** |
| Stable preference key vocabulary | Different names hide duplicates and contradictions | Start with `writing.hashtags`; review a small registry with each new adapter | No: bounded pilot key is chosen |
| Real volume, recall quality, latency, and ledger growth | Assumed limits or scan performance may be unsuitable | Benchmark synthetic 10,000-record fixtures, then measure opt-in pilot misses/latency and deletion volume | No: revise limits through review if measurements fail |
| Secret-filter coverage and user comprehension | Sensitive text may evade patterns; users may misunderstand export/deletion limits | Adversarial synthetic fixtures plus inspect/forget usability review; keep capture conservative | No for spike; **yes for capture rollout validation** |
| User-wide versus project-specific preferences | Incorrect initial scope can surprise users | Pilot project-scoped keys, display scope at capture, evaluate deliberate user-wide selection later | No |

The largest risks are source/memory divergence, mistaken sharing scope, and restoration that bypasses deletion. The ordering above makes those explicit validation gates rather than silent assumptions.

## References

- Pinned public skill observations and the empty repository revision are linked at their claims above; all were inspected on 2026-09-15. No local cache adaptation is treated as the same source revision.
- Official SQLite references inspected: [WAL](https://sqlite.org/wal.html), [atomic commit](https://sqlite.org/atomiccommit.html), [backup API](https://sqlite.org/backup.html), [FTS5](https://sqlite.org/fts5.html).
- Official runtime option inspected: [Node.js SQLite API](https://nodejs.org/api/sqlite.html). Its current API status does not settle the support matrix; pin tested runtime and library versions in phase 1.
