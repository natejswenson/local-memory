> Implemented and activated on 2026-09-19. See [verified deployment status](../fitness-migration-status.md) for the final single-writer architecture, shipped PR, evidence, and remaining desktop observation.

# Plan: migrate local-fitness notes and coach memory to the Obsidian hub

Status: implemented. This document retains the design and red-team history; the [implementation status](../fitness-migration-status.md) and [operations guide](../fitness-memory-operations.md) describe the final architecture.

## Recommendation

Make Markdown in the existing memory vault authoritative for **fitness preferences and the coach journal**, including their archives. Keep the existing fitness tools and prompt assembly, backed by a fitness-specific storage adapter whose transaction and deployment behavior must first be proven. Basic Memory indexes those same Markdown files for shared discovery. Scheduled fitness jobs use the adapter directly, without starting an MCP client, invoking another model, or requiring an OpenAI API key.

Keep SQLite authoritative for Garmin measurements, observations, training plans, report-card snapshots, settings/personality, and the deterministic relationship ledger. The ledger is computed from those sources, not a separate journal to migrate. References from a journal note can identify a brief/activity/report card without copying the full artifact.

Stage the migration: preferences first, coach journal second. Both remain in scope, but a successful preferences migration does not authorize an unproven journal cutover. Keep the journal in SQLite until its independent acceptance gates pass. During staging each record family has exactly one owner; this is not dual writing.

This separates durable prose from operational data while retaining one authoritative copy of each. It changes storage, not fitness grading or model/provider selection.

## What exists today

| Layer | Current owner | Proposed owner |
|---|---|---|
| User preferences | `notes.py`; live `user_notes.md` plus archive | Vault preference notes with preserved provenance and archive state |
| Coach journal, including cold history | `agent/journal.py`; `coach_journal` with FTS | Vault journal notes; rebuildable search index |
| Relationship ledger | `agent/ledger.py`; calculated from SQLite | Unchanged: calculated from fitness data |
| Coach personality and dials | `agent/personality.py` and settings | Unchanged; notes continue to take precedence |
| Workouts, observations, plans, saved cards/briefs | Fitness database/files | Unchanged; linked as sources where useful |

Important source contracts:

- `notes.py`: content-addressed stale-write handles, locked atomic rewrites, newest-first display, 4096-byte live rotation target (existing preservation/error exceptions can exceed it), preservation of undated/freeform text, archive failure must not destroy notes.
- `agent/journal.py`: 240-character entries, 60 hot entries, archive searchable, unique `(source, source_key, seq)` for reflected events, dates distinct from creation order, explicit deletion.
- `agent/memory.py`: one resolver, full/compact limits of 10/3 journal entries, 600-character compact total, `on_or_before` and `exclude_source_key`, fail-soft memory reads and kill switch.
- `agent/reflect.py`: automatic writes after saved briefs/first-render cards; event deduplication prevents repeated generation and self-reflection cache loops.
- `web/mcp_server.py`: persona cache currently observes SQLite changes and ONE notes-file stat. It must detect vault changes after migration.

## Target structure and record contract

Use the existing engine project `local-memory`, and register the note subject `project: local-fitness`:

```text
local-memory/vault/Projects/local-fitness/
  Preferences/<stable-id>.md
  Journal/<stable-id>.md
```

Keep staging, quarantine, migration manifests, operation-recovery state, and backups OUTSIDE the indexed vault, in private ignored runtime storage. A `candidate` flag does not prevent Basic Memory from discovering a file. Do not publish unparsed material until its disposition is reviewed.

Keep identities and filenames stable through archiving. Store archive state in metadata; an Obsidian index note can link active preferences and recent journal entries without becoming another authoritative summary.

Common frontmatter: `title`, `type`, `permalink`, `project`, `status`, `capture_id`, `owner: local-fitness`, `kind`, `source`, and original timestamps. Version the fitness schema. Keep immutable record UUIDs separate from revision handles. Retain original journal integer IDs and source timestamps; use fitness-prefixed provenance fields where engine fields would collide (for example `fitness_source` versus hub `source`). Choose one canonical archive field, with any hub lifecycle value derived and validated against it. Legacy handles belong in the migration manifest; live handles must be recomputed from current timestamp/text, never trusted as permanent editable frontmatter. Preserve source event dates separately from engine timestamps. Engine `modified` is not the historical event date. Preserve the original text verbatim during migration; do not rephrase, re-date, or infer new medical facts.

Distinguish user preferences, user reports, and model-authored coach reflections. A reflection is attributed coach history, not a verified measurement. Existing inferred entries must not become confirmed global preferences merely because they enter the hub. Unsupported/malformed content is preserved outside the indexed vault and counted in the migration report. Compare its current prompt behavior: excluding previously used freeform preferences is a behavior change, not lossless parity. Resolve such cases before switching that record family; never silently suppress them.

Fitness material stays scoped to `local-fitness`; no automatic promotion to `global`. This scope limits retrieval conventions, not access permissions: trusted clients connected to the shared vault can read it. Mount only the fitness subtree into the fitness container so that service cannot browse the rest of the vault.

## Integration design

Add a small storage interface with `legacy` and `vault` implementations. Keep `legacy` as the default for public clones and explicit fallback configuration; this deployment switches each record family once after its migration. Proposed settings:

- Separate preference and journal backend selectors, each `legacy|vault`, with both defaulting to `legacy`. Final names are settled in the spike; a single all-or-nothing selector cannot support the staged cutover.
- `LOCAL_FITNESS_MEMORY_ROOT`: path to the dedicated fitness subtree, required in vault mode.

Never silently create another authoritative store when a configured vault is missing. Read failures can retain today's fail-soft behavior with visible degraded status; requested saves return an explicit failure. Do not fall back to writing the legacy store.

Keep `save/list/update/delete_user_note` and `save/list/recall/delete_coach_memory` as the user-facing tool names. They delegate to the chosen backend, so Claude, Codex, HTTP clients, and scheduled code share behavior. Preserve initial handles and integer journal IDs for migrated records. Recompute handles after edits. Import the existing SQLite `sqlite_sequence` high-water mark, not just surviving row IDs. Journal compatibility IDs need a durable allocation high-water mark that survives deletion and restart; never allocate from the maximum surviving note. Preserve the existing date/ID ordering on ties. Add stable note identities to results without removing existing fields. Stale content handles must still fail rather than overwrite an edited note.

Use Basic Memory for cross-client discovery, but route fitness mutations through existing fitness tools. Skill ownership routing is advisory and insufficient by itself. Before making fitness records live, add and test an application-level guard at the shared hub write boundary: generic writes must reject fitness-owned records and destinations, including overwrite, alternate path/permalink forms, and explicitly fitness-scoped writes elsewhere. This cannot detect arbitrary semantic duplicates disguised as another subject; skill routing remains necessary. Metadata alone must not select ownership. This guard is not an OS security boundary against another process running as the user. If the guard is impractical, stop and revise the integration rather than claiming protected ownership.

Verify that both ChatGPT desktop and a fresh Codex CLI chat outside the fitness repository can actually access the fitness mutation tools. A globally available hub does not imply globally available fitness tools. When those tools are unavailable, return an explicit failure; never fall back to a generic hub write.

Direct Obsidian edits do not honor application locks. Version one supports sequential manual body edits followed by validation, not guaranteed concurrent manual/application editing. Preserve invalid edits as conflicts and report degraded records. A last-moment hash check cannot eliminate the editor-versus-replace race. If overlapping manual editing is required, change the write design before cutover; backups alone are not a no-lost-update guarantee.

For routine injection, resolve a validated fitness snapshot, choose records deterministically, and preserve current budgets. Reuse Basic Memory for indexed discovery where useful, but do not let its asynchronous index determine whether a reflected event already exists or whether a write is safe. No second authoritative SQLite prose store or continuous two-way synchronization. Use a rebuildable local FTS cache for fitness archival recall if the measured corpus needs it; no scheduled job should require the host Basic Memory process. Validate cached hits against current files. Specify freshness checks for deletions and external edits, and benchmark cold rebuilds and warm prompts against actual corpus sizes. Avoid rescanning all archived bodies on each request. Snapshot assembly belongs outside long-lived SQLite transactions; existing `conn=` callers need explicit adaptation, not silent loss of consistency assumptions.

Before adopting the adapter, prove journal insert-plus-archive recovery as one logical operation; per-file atomic replacement is insufficient. Specify an operation log/commit protocol outside the indexed vault, crash recovery before serving reads, and backup/restore of required identity and recovery state. If this becomes a second database implementation, revisit the architecture before proceeding. Also prove exclusive create, lock scope across host/container writers, stale-update detection, and recoverability of interrupted archive/deletion operations. Basic Memory's overwrite guard alone does not prove these guarantees. If Docker Desktop bind-mount locks do not coordinate reliably, stop cutover and choose one shared local writer service; do not ship two uncoordinated writers.

## Implementation sequence

1. **Inventory and freeze the migration specification.** Resolve effective host/launchd/container paths without printing secrets. Count live/archived preferences and journal records, malformed text, duplicate handles/event keys, and byte totals. Confirm whether active jobs share the same data. Record counts/hashes privately, not personal text in tracked fixtures. Use the SQLite backup API or an equivalent WAL-safe snapshot, and lock the preference live/archive pair during its snapshot. Inventory effective overrides, deployed revisions, launch mechanisms, and pending reflection tasks. Perform a restore check.
2. **Build the adapter and synthetic parity tests.** Add `memory_store.py` (interface/config) and `vault_memory.py` (fitness-scoped Markdown I/O). Route `notes.py` and `agent/journal.py` through the backend while keeping legacy behavior unchanged. Use stable IDs, bounded parsing, path containment, sidecar locks, atomic writes, and explicit conflict results. Prove host/container coordination before choosing the final write mechanism. Freeze the schema, integer-ID allocation, operation recovery, deletion semantics, generic-write guard, and search strategy at the end of this spike. Failure of any journal gate defers the journal phase while preferences can proceed independently.
3. **Implement a dry-run migrator.** Produce a private manifest mapping source identity to destination identity, timestamps, archive state, and content hash. Use deterministic migration IDs, including source identity/occurrence where duplicates exist; identical text is not enough to deduplicate events. Re-runs skip verified matches and stop on conflicts. Preserve unparsed material separately and never silently drop it. Import into private staging outside the vault first, then compare counts, text, dates, ordering, and searches.
4. **Wire every consumer and cache.** Update `agent/memory.py`, `reflect.py`, `tools.py`, `status.py`, prompt notes resolution, and `web/mcp_server.py`. Pure prompt builders stay pure; resolve notes outside them. Replace the single-file persona-cache signature with a subtree revision/fingerprint that catches external edits, renames, archive changes, and deletions. No unrelated vault note may invalidate a fitness prompt. Keep self-source exclusion and historical date behavior. Preserve the existing personality precedence and memory kill-switch semantics.
5. **Cut over once per record family.** Disable scheduled launches and stop/drain all memory writers, including HTTP/MCP processes, pending reflections, and old checkout/container instances. Record stopped runtime identities and prevent old revisions from restarting. Snapshot again, import the final delta, verify, set the selected family to vault mode on every deployment, mount the fitness subtree at a configurable container path, then restart and verify effective configuration. Keep separate read-only rollback snapshots; the operational fitness database itself must remain writable. Retain the old journal table without active writers. No ongoing dual writes. Rebuild/smoke-test the container from tested `dev`, per repository guidance.
6. **Validate real use and retire legacy writes.** Compare selected before/after preferences and journal searches. Test a new note, stale update refusal, Obsidian edit, archival recall, and explicit deletion through fitness tools; verify shared desktop/CLI discovery. Generate local synthetic brief/card outputs and check prompt budgets/cache stability. Observe the next scheduled run and confirm a consistent backup includes fitness notes plus any required allocator/tombstone/recovery state, and restore it in isolation. Remove transitional reader code only after the observation period; retain the backup and mapping manifest under the retention policy.

## Acceptance criteria

- Every source record is accounted for: migrated verbatim, archived, or preserved for review. No unexplained omissions or inferred deduplication.
- A replayable failure matrix covers concurrent duplicate creation, crash during insert/archive, persisted write with lost reply, allocation followed by deletion/restart, and manual-edit conflicts. Generic hub mutations cannot bypass fitness ownership rules.
- Existing handles/IDs target the same records; stale handles fail. Interrupted writes/retries cannot produce duplicate event memories or destroy archived content.
- Both hot and archived journal retrieval work; routine injection excludes archived/candidate/malformed entries as intended. Search ranking differences are evaluated, not promised identical to SQLite BM25.
- Historical `today` filtering and current archive semantics remain as implemented; do not claim fully versioned time travel the current code does not provide. Same-card exclusions and deterministic sorting keep prompt hashes stable across unrelated edits.
- 600-character compact budget, 10/3 entry limits, preference limits, 240-character journal limit, and memory kill switch remain covered by tests.
- No model/network calls for storage or tests; no new OpenAI API key. Existing inference-provider settings remain unchanged.
- Host CLI, launchd, stdio MCP, HTTP MCP, and Docker see the same authoritative fitness subtree. A stranger's unconfigured clone still works in legacy mode.
- Relevant tests plus full `uv run pytest -x`, Ruff, 85% coverage, docs/tool-registry drift checks, and affected performance benchmarks pass. Do not rebaseline away added I/O. Prompt composition changes require the repository's prompt/evaluation checks. Deployment verification includes actual container behavior, not only image build.

## Rollback and deletion

Before any post-cutover write, switching back to the frozen legacy snapshot is straightforward. After new writes, pause writers and export the changed vault records back through a verified reverse migration, preserving IDs/archives/deletions; never simply flip to stale SQLite. If reverse compatibility cannot be established, keep vault ownership and repair the adapter. Backups and migration snapshots may retain deleted content until retention expires; fitness reads must exclude a deleted record immediately. Generic hub search may lag; before claiming deletion is complete across clients, demonstrate index invalidation or fresh-file filtering and verify both desktop and CLI recall. Stale search snippets also count as retained content.

Existing journal deletion is a hard delete, and `has_event` checks remaining records: deleting an event’s last entry can permit reflection again. Tombstones would deliberately change that contract. Keep current behavior for the initial migration, with a documented exception to the generic hub preference against resurrection; migration manifests must still prevent re-import of records deleted after cutover. Add event tombstones only as a separately specified behavior change, with backup and rollback support.

Prove reverse export with synthetic post-cutover creates, edits, archives, and deletes BEFORE switching. Reject unsupported manual schema/body changes explicitly rather than promising a lossless downgrade. Restore only the affected notes/journal records into the current operational store; never replace the whole fitness database with an old snapshot and discard intervening workout/settings changes.

## Expected change sets

Use reviewable PRs into `dev`: (1) feasibility spike and explicit contracts; (2) preference adapter, migration, and consumer wiring; (3) journal adapter and migration after its gates pass. Track host cutovers as private operational checklists, not commits containing personal manifests. Shared-hub write guards and global client routing are separate coordinated changes in local-memory, required before publishing fitness records. Update `.env.example`, `docs/deployment.md`, affected `docs/mcp/` pages, README, CHANGELOG, and canonical `CLAUDE.md` together. Register the fitness subject and ownership routing in the hub's conventions/skill at cutover.

The first implementation task should be the inventory and adapter spike. It will settle record counts and cross-process locking before committing to migration mechanics. No health advice or fitness-data interpretation is part of this storage migration.

## Red-team findings and release gates

Reviewed against source, not deployed processes or private records. These are plan defects and unproven guarantees, not claims of observed production data loss.

| Priority | Finding | Required resolution |
|---|---|---|
| High | Multi-file Markdown does not inherit SQLite uniqueness, allocation, or insert/archive atomicity. | Crash-tested transaction/recovery design; journal stays legacy until proven. |
| High | Generic hub writes and manual editor writes bypass fitness locks and stale-write checks. | Enforced generic-write guard; explicit sequential manual-edit contract; cross-client mutation availability test. |
| High | In-vault quarantine is still searchable, and excluding freeform notes can silently change prompts. | Private off-vault staging and explicit disposition of every affected record. |
| High | Stopping one process or changing env does not stop old writers; restoring the full old DB loses unrelated new data. | Inventory/drain/fence all deployments; per-family cutover and record-scoped reverse migration. |
| Medium | IDs, lifecycle fields, engine timestamps, and revision handles can diverge. | Versioned schema, one canonical archive field, source dates, durable ID high-water mark, computed handles. |
| Medium | Full-history scans and stale indexes can break prompt latency or return deleted text. | Measured cache strategy, fresh-file validation, cross-client delete checks, cold rebuild benchmarks. |
| Medium | Existing reflection writes are partial batches, not an all-or-nothing event. | Preserve and document current behavior initially; do not claim full-event retry recovery. A batch-completion protocol is separate work. |

Source anchors: `local-fitness/src/local_fitness/notes.py` (`_handle`, `_locked_rewrite`, `append_note`, `update_note`); `agent/journal.py` (`save_entry`, `has_event`, `delete_entry`, `archive_overflow`); `agent/reflect.py` (`_reflect`); `agent/memory.py`; `web/mcp_server.py`. The hub's `skills/local-memory/SKILL.md` explicitly describes native write/lifecycle restrictions as advisory.

Recommendation after review: proceed with inventory and the bounded feasibility spike, then preferences. Do not begin journal cutover on the strength of this document alone. The objective remains one Obsidian-backed home for fitness prose, with complexity and failure behavior demonstrated before replacing existing guarantees.

## Second red-team pass: additional required contracts

This pass inspected the installed Basic Memory indexing/storage code as well as fitness source and the hub backup script. The findings below extend the earlier gates; they are not implemented fixes.

### 1. The indexer is another potential writer — high priority

The installed Basic Memory `indexing/batch_indexer.py::_normalize_markdown_file` can write frontmatter during sync, including permalink normalization. `services/file_service.py::update_frontmatter_with_result` reads and replaces the complete file; its current implementation uses `content.strip()` when rebuilding the body. Thus “discovery only” does not establish read-only indexing or byte-preserving import. MCP write guards alone cannot prevent this path from racing a fitness write.

The spike must show that the configured fitness indexing path does not rewrite fitness files, including first indexing, missing metadata, duplicate permalinks, rename, rebuild, and concurrent MCP startups. Where normalization cannot be disabled or coordinated, stop direct shared indexing and revisit the architecture. Do not silently patch the installed dependency or weaken unrelated hub behavior. Preserve raw source bytes privately and separately test exact logical text round trips through YAML/Markdown; do not claim raw-file byte equivalence after format conversion.

### 2. Recovery state is authoritative too — high priority

An ID allocation high-water mark and committed-operation records cannot always be reconstructed from surviving notes after deletion. Label only the search cache disposable. Define a required, versioned fitness control-state directory outside the indexed vault, and a store UUID binding that state to its note subtree. Every host/container writer must use the SAME control-state directory and lock inode; container-local `.runtime` directories would defeat coordination even with shared notes. A missing/mismatched control store must refuse writes, not initialize another one. Configure and mount only this additional fitness-specific directory, not the whole hub runtime.

The current `scripts/vault_backup.py` selects only Markdown and `.obsidian/` within the vault, and explicitly is not an atomic filesystem snapshot. It does not back up this proposed control state. Before cutover, implement a coordinated snapshot of notes and control state at the same committed revision, preserving compatibility with existing hub backup/restore. Restore must validate store UUID, schema, record counts/hashes, and allocation floor before enabling writes. A vault-only restore must not silently reset identity history. Test missing sidecar state, interrupted backup, disk-full failure, and failed retention cleanup; retain the previous good backup. Define a maximum acceptable backup age and expose failures in status.

### 3. All readers need the commit boundary — high priority

A transaction log used only by the fitness adapter does not stop Basic Memory from indexing half of a multi-file insert/archive operation. Define visibility for fitness reads, generic `read_note`, search snippets, and `recent_activity`. Require a validated committed revision for any claim of a consistent snapshot. If native indexing cannot honor that boundary, document and test eventual consistency for generic discovery and require fitness-tool validation before using fitness evidence. Do not imply instantaneous cross-client agreement. Prefer a simpler write design if enforcing this demands a second transaction system.

### 4. Invalid files remain visible to the generic hub — high priority

An off-vault importer quarantine does not solve later invalid Obsidian edits. A fitness adapter rejecting an oversized body, duplicate ID, unknown schema, or bad archive field does not stop generic Basic Memory indexing the same file. Add a shared validation path or explicit owner-specific validation during recall; until validation succeeds, no client may treat the record as current fitness evidence. A candidate flag or advisory `owner` is insufficient to promise enforced filtering. Do not silently move or overwrite a user's open file to quarantine it.

Use bounded safe YAML parsing, reject duplicate keys and ambiguous scalar types for identity/date fields, and round-trip quoted dates, numeric-looking source keys, Unicode, newlines, and delimiter-like body text. Reject symlinks and non-regular files at the adapter boundary. Detect copied notes with duplicate UUIDs/permalinks; never choose whichever is scanned first. Version one supports body edits at stable paths; rename/move, metadata changes, and copy-as-new need explicit validation and must not silently create or delete records. In-vault operational diagnostics must not become evidence or leak into prompts.

### 5. Migration identity and budgeting need exact definitions — medium priority

For journal migration, derive identity from a stable source-store identity and original integer ID, never text alone. For preference migration, freeze a private source snapshot and occurrence mapping: line positions and text hashes can change when the live file rotates or is edited. Final reconciliation must handle updates and deletions as well as additions. If source changes make mapping ambiguous, rebuild the unpublished staged import from a new locked snapshot rather than guessing. Never replay an initial import over a live destination after cutover.

Preserve the 4096-byte preference rotation calculation using the equivalent legacy payload, not the new files' YAML overhead or directory byte count. Preserve the just-updated note's eviction protection, duplicate-handle behavior, freeform text, and deterministic tie ordering. Separate storage rotation from rendered prompt budgets. Freeze clock semantics: current journal creation uses local time/date while `days` uses SQLite UTC `date('now')`; migration must not silently unify them. Include UTC/local midnight, DST, backdated entries, and same-date ID ties in parity fixtures.

### 6. Shared integration must stay narrow and usable — medium priority

Do not globally enable every fitness tool merely to make memory editable: the existing MCP server registers `ALL_TOOLS` and installs coach persona/resources. Use an explicit supported memory-tool subset for shared access, test both advertised schemas and call dispatch, and keep unrelated fitness mutations and automatic persona injection out of ordinary chats. Preserve existing authenticated transport settings. Check tool-name collisions and prove tool availability in a fresh desktop chat and an unrelated-directory CLI chat. Subscription-only applies to the memory integration; it does not authorize changing existing fitness inference providers.

Explicitly register `local-fitness` as the subject when the user asks about fitness from a desktop chat with no working directory. Shared recall must resolve owner-specific fitness corrections and archive state instead of requiring generic `key`/`supersedes` metadata the legacy tools do not produce. Avoid injecting the same preference/journal through both fitness persona and shared recall; retain provenance for model reflections, and test adversarial note text as data rather than instructions.

### Completion evidence

The next implementation stage must produce a gate matrix with a named check, evidence location, and pass/fail result for each contract above and in the first review. No “implemented” box substitutes for a tested outcome. In particular, demonstrate end-to-end sequential create/read/edit/archive/delete across Obsidian, fitness tools, desktop, and CLI; recovery after a persisted-but-unacknowledged write; and an isolated restore followed by a new ID allocation.

This remains a source-based planning review. At review time runtime behavior had not been tested. The subsequent implementation status records the measured results; production adapter recovery and cross-client cutover remain unproven. Another prose review cannot establish those facts; the bounded spike is the next useful step. If direct Markdown journal authority requires extensive transaction machinery, present the simpler alternative explicitly: SQLite-owned journal with an Obsidian read model, acknowledging that it changes the requested authority model and requires a revised decision before adoption.
