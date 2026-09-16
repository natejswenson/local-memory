# Local memory operations

## Install and support

This is an unpublished, private npm package. From this checkout, `npm ci
--ignore-scripts` prepares the dependency-free package; `npm pack` creates a
local tarball that can be installed with `npm install --global ./TARBALL.tgz`.
No publication is needed. `local-memory` and `local-memory-adapter` must resolve
to this trusted installation, with Node on PATH. The CLI uses argument arrays
and bounded stdin JSON; it does not evaluate memory text.

Node >=25.2.1 **and loaded SQLite >=3.51.3** are required. Pin Node 26.8.2 for a
stock runtime; its observed SQLite is 3.53.4. `node scripts/compatibility.mjs`
checks the actual loaded library. See [support evidence](compatibility/README.md)
for observed hosts; an installed host executable alone is not a passing test.
Windows and no-process/no-filesystem hosts are unsupported. The implementation
uses POSIX owner permissions. Network and synchronized paths are unsupported;
known path patterns and symlinks are rejected, but detection is imperfect.
Choose a local fixed disk yourself.

Data is independent of package/skill installations:

- macOS: `~/Library/Application Support/local-memory/`
- Linux: `${XDG_DATA_HOME:-~/.local/share}/local-memory/`
- An explicitly configured absolute `LOCAL_MEMORY_HOME` overrides the default.

Set the same override in every host's trusted environment. Changing that value
is not a migration: ordinary recall never creates a store. Use explicit setup
only for a deliberately new store. Relocation must preserve the **entire**
quiescent directory, including its current deletion journal and identity; never
copy a live database alone or initialize a replacement to mask missing data.
Do not derive the override from a repository or recalled content.

## Setup

All examples are synthetic. Every `manage` command is an explicit local user
management action, not an authorization surface for model-generated content.
Send one JSON object on stdin:

```sh
printf '%s\n' '{"protocol":1,"op":"init","request_id":"setup-1","backups":false}' | local-memory manage
```

Initialization creates 0700 directories and 0600 files. It records a random user
namespace, registry, receipt hashing key and backup choice. Ordinary recall does
not initialize or repair storage. No encryption or same-OS-user sandbox is
claimed. Package install/upgrade/removal does not own this data directory.

Register a user-selected canonical project root with `manage`:

```json
{"protocol":1,"op":"project","request_id":"project-1","project_id":"prj-harbor","roots":["/absolute/user-selected/project"]}
```

Roots must exist and resolve without symlink substitution. Descendants inherit
that root; the longest matching root wins. Ambiguous identical roots assigned to
different projects are refused. A separate clone/worktree needs explicit setup.

Register adapters using their `setup` command. Ghostwriter requires an existing
user-selected voice-note file; it does not search private stores:

```sh
local-memory-adapter ghostwriter setup < ghostwriter-setup.json
local-memory-adapter writing-peer setup < peer-setup.json
```

Ghostwriter JSON is `{"source_id":"voice","source_path":"/absolute/selected/voice-notes.md"}`;
peer JSON is `{}`. These setup actions opt in capture. Install the companion
[ghostwriter instructions](../adapters/ghostwriter/SKILL.md) and
[second-client instructions](../adapters/writing-peer/SKILL.md) in the host's
user skill directory only when deliberately enabling the companion. No host or
live source store was activated during implementation. Existing source skill
contracts remain authoritative; upstream automatic adoption is not performed.

The trusted adapter injects identity, registration token and actual project
scope. Raw protocol examples require the same trusted injection; never ask a
model to supply identity, authorization or project labels.

## Management and protocol

`local-memory request` accepts adapter operations; `local-memory manage` is the
local user's explicit management entrypoint. Both read one JSON request and emit
one compact JSON response. Required envelope: `protocol: 1`, `op`, and bounded
ASCII `request_id`. Adapter requests additionally carry `caller` with registered
`skill_id`, `user_id`, `token`, and `project_id` (or null). Mutations require a
bounded `idempotency_key`. Unknown fields are rejected.

| Operation | Additional fields / behavior |
| --- | --- |
| `status` | Reports location, schema, pressure and storage state; counts are management-only |
| `register` (manage) | `skill_id`, selected `keys` (max 64), boolean `capture` |
| `project` (manage) | `project_id`, canonical `roots` (max 16) |
| `source` (manage) | `source_id`, `owner_skill`, selected absolute `path` |
| `remember` | `record`: type, registered key, content, provenance; optional sharing/deadlines/status/mirror |
| `recall` | Nonempty `keys` or `query`; optional `types`, `limit`, `max_context_bytes`, `retrieval_mode` |
| `show` | `id`; recipient scope still applies outside management |
| `list` (manage) | Optional `project_id`, `owner_skill`, `offset`, `limit` (1–50) |
| `update` | `id`, `expected_version`, `changes`; immutable identity/scope cannot move |
| `forget` | `id`, `expected_version`; durable deletion and managed-copy purge |
| `selection` (manage) | Displayed `id`/`expected_version` or creating `owner_skill`/`project_id`, exact `recipients`; returns a 5-minute token |
| `export` (manage) | Explicit `project_id` and/or `owner_skill`; same bounded pagination; optional `format: json/markdown` |
| `backup` (manage) | Creates a validated managed snapshot, returns snapshot name |
| `restore` (manage) | `snapshot` name; verifies current journal, resets every sharing grant before publication |
| `migrate` (manage) | Mandatory validated backup, transactional migration; v0 is the same bootstrap table layout without the v1 marker |
| `maintain` (manage) | Purges expired records through deletion protocol, checkpoints and compacts |

Revocation is `update` with `changes: {"share_with":[]}` and the expected version.
New grants require a selection token bound to the record/version and recipients;
model-authored `share_with` alone is refused. Mirror edits must use the owning
adapter; direct management edits of a mirror return `SOURCE_REQUIRED`.

Provenance contains `kind` (`explicit_user`, `explicit_correction`,
`confirmed_fact`, `inferred`), `skill_version`, opaque `source_ref`, and ISO
`observed_at`. Source references cannot be paths, URLs or instructions. Inferred
records remain private suggestions, expire in seven days and never enter recall.
Explicit value changes require correction provenance. Facts/context require
confirmation and expire within 90 days; preferences review within 180 days,
facts/context within 30. Reads never renew deadlines. Management shows stale and
expired state; normal recall excludes both before conflict processing.

Exact dedupe compares canonical NFC content/metadata, normalized newlines,
trimmed outer whitespace and sorted recipients. A differing duplicate requires
explicit versioned update. The engine never retains old content versions.

Exit codes: 0 success; 2 invalid input; 3 storage/unavailability; 4 policy or
conflict. Errors have safe codes and no rejected content. `INVALID_REQUEST` is
used for context-budget bounds; other schema errors use `INVALID_INPUT`.
Absent recall is successful `storage: absent`; writes return `NOT_INITIALIZED`.
Missing initialized DB, corruption, inaccessible storage and incompatible schema
are separate errors. A failed save must never be described as remembered.

Reuse the same mutation key after lost acknowledgment. Receipts retain a keyed
payload digest and content-free result for 30 days (maximum 100,000 live
receipts); they commit with the mutation. Different payload/same key conflicts.
Forgotten targets return `GONE` on old save replay. After the receipt window,
inspect state before creating a new mutation key. Tombstones persist indefinitely.

## Budgets and trust

Requests are <=16 KiB; text <=2 KiB UTF-8; metadata <=2 KiB. Live records <=10,000,
database/index pages <=100 MiB. Default recall is five records/4096 bytes;
maximum ten/8192. Accepted context budgets are 64–8192 bytes. Whole entries are
omitted deterministically, and `omitted_count` counts only eligible resolved
records and conflict keys omitted by count/bytes. Inspection pages are <=50
records/128 KiB and must not be injected wholesale into a task.

FTS5 uses `unicode61`, escaped literal-token conjunctions and bound parameters.
Scan mode uses NFC/lowercase Unicode letter/number tokens, without stemming.
Scope, review/expiry and source freshness precede candidate groups. A lexical
match expands to all eligible same-type/key competitors before correction and
project precedence. Equal-precedence conflicting values withhold the key.
Free-text tokenization may differ between modes; exact keys have the same scope
and resolution semantics. No semantic contradiction detection is claimed.

Recalled text is untrusted data. Current instructions win. It cannot open its
source reference, execute code, change tool permissions, publish, message or
otherwise authorize external action. Secret-pattern rejection is defense in
depth, not a guarantee that arbitrary sensitive text can be safely auto-captured.

## Recovery and rollback

See [durability protocol](recovery.md). Backups are opt-in, at most one daily
pre-mutation snapshot, plus explicit/mandatory migration snapshots; retain at
most three, each <=100 MiB, for at most 30 days. A failed requested snapshot is
visible; failed mandatory migration backup prevents migration. Corruption never
triggers an empty reset or automatic restore.

Forget removes memory copies and purges every managed backup/quarantine copy.
A pending purge suppresses content reads until retry succeeds. Physical cleanup
may remain pending while a reader holds the WAL. This is not forensic SSD
secure erasure. Exported files, OS snapshots, user copies and prior host
transcripts are outside deletion control; whole-directory OS rollback is not a
supported restore. Export includes this warning and the deletion sequence and
has no bulk-import path.

`local-memory-adapter ghostwriter disable` with `{}` disables the companion and
leaves voice notes usable. Enable again with `enable`; it retains forgotten-event
suppression. Adapter capture writes a source-event marker into the selected
notes before mirroring. Failed mirroring reports pending sync. Reconciliation is
explicit per selected key and never resurrects a forgotten mirror. Removing a
source preference itself remains the original source skill's responsibility.
