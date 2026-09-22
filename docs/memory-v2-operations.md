# Local memory v2 operations

The small stdio server serves current general memory, activity history, and optional
skill preferences from the existing vault. Client configuration is independent of
storage. The old Node SQLite package, fitness ownership, and existing capture IDs
are unchanged. No cloud endpoint, API billing, model download, or uploader is added.

## Commands and compatibility

```sh
bin/memory-hub status --all --json
bin/memory-hub doctor --all --details --json
bin/memory-hub clients list
bin/memory-hub connect --client opencode --mode pilot
# Use the exact plan hash returned above after reviewing the owned changes.
bin/memory-hub connect --client opencode --mode pilot --apply --expect-plan HASH
bin/memory-hub verify --client opencode
bin/memory-hub verify --client opencode --synthetic
bin/memory-hub recall --subject global --query 'relevant decision'
bin/memory-hub capture --request /absolute/request.json
bin/memory-hub capture --request /absolute/request.json --apply
bin/memory-hub activity recall --stream outcomes --skill example
bin/memory-hub activity record --request /absolute/event.json
bin/memory-hub index status
bin/memory-hub index reconcile
bin/memory-hub maintenance run --once
bin/memory-hub backup status
```

Commands emit JSON with a stable `code`. The existing scripts remain compatible
for this release. A nonzero exit means a partial, invalid, or unavailable operation;
inspect the code instead of treating empty records as proof that memory is empty.
The plain legacy `doctor` output remains available. Both doctor paths are read-only.

`mcp --tool-profile core` exposes five tools: `memory_status`, `recall_context`,
`capture_memory`, `record_activity`, and `recall_activity`. `core+skills` adds the
existing typed `skill_memory` contract. Native inspection is a separate process:
`mcp --tool-profile inspection`; the raw-write test surface requires
`mcp --pilot --tool-profile pilot-inspection`. Native inspection retains the
foreground index freshness barrier. Bare `mcp` retains the legacy combined surface
for existing registrations during the compatibility release.

## Client configuration and coverage

Adapters cover Codex, Claude Code, Claude Desktop, OpenCode, and the default VS Code
user profile. Codex IDE/ChatGPT desktop and Claude Code IDE are tracked as separate
surfaces sharing a configuration binding. Ollama runs through the OpenCode host.
Discovery reports installed unsupported apps rather than claiming they work.
Alternate named profiles are refused until an explicit adapter is available.
Project overrides and client-specific trust prompts still require host verification.

Install plans list changed paths and before/after hashes without dumping settings.
JSONC editing preserves unrelated bytes and comments; duplicate keys, symlinks,
unmanaged same-name entries, and stale plans fail safely. Exact before-images and
per-file journals live under ignored `.runtime/integration-backups/`.

```sh
bin/memory-hub disconnect --client opencode --mode live
bin/memory-hub disconnect --client opencode --mode live --apply --expect-plan HASH
bin/memory-hub rollback --operation UUID
bin/memory-hub rollback --operation UUID --apply --expect-plan HASH
```

Rollback restores only files still matching that operation's output. Newer user
edits require review. Relevant server, model, routing, and instruction changes invalidate old verification.
App-maintained counters do not invalidate an unchanged MCP transport. A Python
transport probe establishes `reachable`; it never establishes `host_verified` or
`workflow_verified`. The synthetic command launches isolated MCP processes and
checks discovery, nonce recall, capture, exact retry, cross-client correction,
disconnection, and restart. It does not invoke the named app's agent or local model.
Actual app/model evidence must be recorded separately with persisted result hashes.
`verify --client CLIENT --evidence FILE` imports an explicitly labeled operator
attestation only after checking its existing synthetic capture receipt. It never
manufactures a missing return artifact.

## Upgrade the durable controls

Install the writer-compatible code before enabling new storage features. Stop or
restart all older hub writer processes. A version marker cannot constrain code that
predates the marker. Existing user apps can remain open; their memory connections
must reconnect. Do not enable features based only on an edited registration.

Take and verify a coordinated backup, including general and skill controls. Place
verified, recent evidence in private `general-memory` control files:

- `writer-upgrade-evidence.json`: `verified`, `vault`, timezone-aware `checked_at`,
  `minimum_writer_version: 2`, `legacy_writers_stopped: true`, and evidence references.
- `backup-restore-evidence.json`: `verified`, `vault`, timezone-aware `checked_at`,
  and the verified archive/quarantine references.

These are records of checks actually performed, never switches to bypass them.
Live activation refuses absent or older-than-24-hour evidence. Synthetic profiles
are exempt from the personal upgrade gates.

```sh
bin/memory-hub features
bin/memory-hub features --apply --expect-plan HASH
bin/memory-hub index reconcile
bin/memory-hub maintenance run --once --full
bin/memory-hub maintenance install
bin/memory-hub maintenance install --apply --expect-plan HASH
```

The job installer prepares one owned LaunchAgent. Load/reload it explicitly through
launchctl after inspecting its configuration. It runs every five seconds, coalesces
sequence changes, and performs full reconciliation every five minutes. Existing
publisher import jobs retain their source ownership and idempotent IDs.

`catalog` previews adoption; `catalog --apply --expect-plan HASH` creates durable
membership without rewriting notes. Freeform notes remain outside that membership.
Missing, malformed, or structurally changed managed records retain their correction
membership as withheld evidence. A broken terminal cannot revive an ancestor.
Missing catalog controls fail closed. Back them up; they are not a rebuildable cache.
After adoption, do not disable the catalog or downgrade to a reader that ignores it.

## Activity and derived views

Activity Markdown and receipts remain authoritative. A private SQLite/FTS5 database
indexes metadata and text. New source commits carry durable sequence intents; the
reader catches up before returning a complete result. Selected results are read and
hash-verified again. Backlogs, modified sources, missing FTS5, corrupt caches, and
stale reconciliation have distinct partial/unavailable outcomes.

`stream=all` preserves existing tool behavior. Skill workflows use `outcomes`;
`telemetry` selects tool-call history. Time-ordered pages use a bounded insertion
snapshot and keyset position. Search pages retain up to 5,000 ranked IDs for fifteen
minutes, binding cursors to filters so new corpus statistics cannot reorder a page.
Change the query or wait past expiry and start a new cursor. An oversized first
record returns a budget warning without an infinite zero-progress cursor.

```sh
bin/memory-hub index rebuild
bin/memory-hub changes
bin/memory-hub changes --apply --expect-plan HASH
bin/memory-hub views refresh
bin/memory-hub views refresh --apply
```

Cache rebuild quarantines the prior cache and streams verified sources. Change-log
recovery commits only provable source publications. Missing pending sources remain
review blockers and are never recreated. The worker renders Atlas outside the
source lock, writes only changed pages, and preserves manual regions with recovery
copies. Activity navigation uses reconciled index metadata, so it can lag source
edits; it is never advice evidence. Large daily pages show at most 200 outcomes and
state how much history remains in the source journal. General knowledge embeds
continue to validate current managed sources before publication.

## Backup capacity and recovery

Legacy v1–v3 ZIP and encrypted v1 restores remain supported. Explicitly configure
v4 in private `operations.json`, preserving other fields:

```json
{
  "schema_version": 1,
  "backup_destination": "/absolute/private/backup-directory",
  "backup_format": "v4",
  "max_logical_bytes": 8589934592
}
```

V4 uses at most 32 MiB of source input per ZIP part, contiguous fragments, per-file
and per-part checksums, and a bundle identity. It streams source data and verifies
source signatures before/after the snapshot. Complete bundles have a final manifest;
interrupted staging directories are retained for inspection. V4 does not silently
apply the legacy ZIP retention rule to multipart or encrypted directories.

```sh
bin/memory-hub backup create
bin/memory-hub backup create --key /absolute/separate/recovery-key
bin/memory-hub backup verify --archive /absolute/bundle --quarantine /absolute/new-directory
```

Encrypted v2 recovery authenticates each part and an ordering manifest with Fernet.
The key stays separate. Fitness-bearing encrypted bundles require a matching fitness
owner archive. Restores refuse swapped, truncated, missing, oversized, or unsafe
parts, use a new quarantine, and never activate or merge historical data. Run the
existing restore audit against current forgetting ledgers, receipts, and managed
catalog membership before any promotion. A restored catalog retains its original
vault binding; quarantine is not a newly activated installation.

Backup status resolves the real destination from private operations configuration
or the owned backup LaunchAgent. Logs are not counted as backup archives. Archive
age is separate from restored-integrity evidence.

## Validation and rollout acceptance

Run the complete hub suite with optional fitness source configured, the existing
50 retrieval cases, and the separate frozen twelve-case supplemental corpus.
Semantic evaluation uses the already provisioned offline model; no threshold was
changed for the supplemental corpus. Scale benchmarks are synthetic and exclude
model response generation.

```sh
.venv/bin/python -m unittest discover -s tests/hub
.venv/bin/python scripts/evaluate_recall.py
.venv/bin/python scripts/evaluate_recall.py --held-out
bin/memory-hub benchmark --suite scale --output .runtime/benchmark.json
```

Record actual app/model round trips separately. During a seven-day live observation
period, inspect worker age, source-review issues, backup age, restore evidence,
changed configuration, and reconnect behavior. The worker retains bounded
five-minute operational samples in private `maintenance/observations.json`. A passing one-turn test is not a
completed seven-day observation period. Optional shared daemons, persistent vector
stores, named-profile support, and automatic cloud uploads remain outside this
rollout.

Client configuration sources: [OpenCode configuration](https://opencode.ai/docs/config/)
and [CLI environment controls](https://opencode.ai/docs/cli/). These describe the
provider allowlist and isolated runtime overrides used for local model probes.
