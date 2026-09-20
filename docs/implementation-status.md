# Implementation status — 2026-09-19

## Central skill activity

The [activity integration](central-activity.md) adds validated recording/recall,
Obsidian activity views and automatic five-minute import of the LinkedIn/X success
logs. The first import saved 31 LinkedIn and 9 X records; launchd repeated the sync
successfully with no duplicates. The user reported trusting the installed Codex
PostToolUse hook; native hook execution still requires an observed host event.
Existing clients must reconnect to receive the expanded MCP tool allowlist.

## Earlier workflow improvements

Current workflow improvements add offline hybrid recall, validated capture with durable
retry receipts, Obsidian Bases and Scratch/Clippings, 50-case synthetic evaluation,
coordinated control snapshots and an encrypted Google Drive recovery copy. See the [current workflow guide](memory-improvements.md).
The initial activation evidence below remains historical; its native-tool advisory
limits apply to raw search/read, while `recall_context` enforces its documented
scope, lifecycle and byte-budget checks.

**Subscription-only local setup activated.** The user completed the ChatGPT desktop native-MCP round-trip; the persisted return note was independently read and searched from a fresh Codex CLI session. Initial activation configured no API keys, billing or public endpoint. The later
user-selected Google Drive backup contains encrypted recovery archives only.

## Current improvement verification

- 121 hub tests pass; the 50-case hybrid retrieval suite passes with no unexpected evidence.
- Read-only restore auditing now compares current general capture receipts and files
  as well as the skill forgetting ledger; regression tests cover deletion, edits,
  pending receipts, path validation and concurrent changes.
- Nine fresh synthetic MCP checks pass, including retry after restart/reindex.
- Fresh live MCP advertises `capture_memory` and `recall_context`, with raw writes hidden.
- Private Drive download matched SHA-256 and restored 132 hub files and 62 fitness records
  into a new quarantine; no restored state was activated. Cloud uploads remain manual.
- All six user-selected kepano Obsidian skills are installed at a pinned revision,
  validated and routed from the local-memory skill and repository instructions.

## Initial installation (historical evidence)

- Canonical personal vault: `/path/to/local-memory/vault`. No private notes or transcripts were imported. The first real capture is the explicit subscription-only decision for this hub.
- Basic Memory 0.23.2 and dependencies pinned in `uv.lock`. Upstream requires FastMCP 4.0.0b1, explicitly pinned.
- Local stdio launcher validates isolated configuration and paths, uses polling for external edits, and completes indexing before serving the first read. Embeddings, telemetry, cloud routing, and auto-update are disabled.
- Shared default `~/.codex` server is **enabled in live mode**, alongside the local-memory skill and global bootstrap instructions. Existing unrelated settings are preserved, with initial backups in `~/.codex/local-memory-install-backup/`.
- Live activation completed using the user's desktop verification attestation, the persisted return note, and passing engine/recovery evidence. The installer supports disabled, pilot, and live modes and preserves the selected mode on rerun.
- Daily launchd backup `com.local-memory-hub.backup` is installed and loaded. It snapshots the canonical vault at load and every 86400 seconds while the user session is available, retaining 14 snapshots in `~/Library/Application Support/local-memory-hub/backups`. The first run exited 0 and saved both setup files. Logs: `.runtime/live/backups/`.

The legacy globally installed local-memory package remains separate and untouched; its status reported zero live records. The vault and runtime are excluded from Git and protected by repository instructions.

## Initial verification (historical evidence)

- 19 unit tests pass: installation preservation/idempotency/modes, symlink/configuration boundaries, activation gating, scheduled-backup installation, archive integrity, and quarantined restore.
- Live capture through the installed skill passed: `doctor` was ready, the explicit subscription-only decision was created once with native MCP, and exact content/metadata were verified by readback and search. Evidence: `.runtime/live-acceptance.jsonl`.
- The loaded backup job ran again successfully and its snapshot includes the real note byte-for-byte (`.runtime/live-backup-evidence.json`).
- Native MCP engine checks pass for metadata, filtered search, overwrite conflicts, concurrent writes, persistence, offline edits visible on first read, and live edits within five seconds. Current evidence: `.runtime/engine-probe.json`.
- A fresh Codex CLI chat outside this repository created/read/searched a synthetic fixture using the enabled default memory registration, without memory-server overrides. Evidence: `.runtime/subscription-pilot.jsonl`.
- Three isolated failure checks passed: external deletion followed by reindex/restart removed read/search results; disconnect-before-reply retries at two timings produced exactly one note with exact content/metadata. Both interrupted writes were absent before retry, so persisted-but-unacknowledged and hard-crash cases remain unproven. Evidence: `.runtime/failure-recovery-evidence.json`.
- Restored 48 synthetic files byte-for-byte from a snapshot outside the repository, then independently restored/reindexed and retrieved a known note through MCP read/search in 4.85 seconds. Evidence: `.runtime/recovery-evidence.json` and `.runtime/recovery-index-evidence.json`.

## Activation evidence

The user reported native MCP fixture read and return-note creation from ChatGPT desktop. Its return identity is `the recorded synthetic desktop return identity`; the persisted note contains the expected fixture value. A fresh CLI independently read and searched the exact note (`.runtime/desktop-return-cli.jsonl`). Desktop actions are user-attested; they were not controlled or directly observed by computer automation.

The activation record in `.runtime/live/activation.json` includes the return-note hash and timestamp. `doctor` reports `ready:true`, `mode:live`. Synthetic notes remain isolated in the pilot vault. Restart desktop MCP connections and existing CLI sessions so they pick up the live configuration.

ChatGPT web is not connected. The original Secure MCP Tunnel proposal was superseded by the user's subscription-only constraint. Developer mode remains on from the approved setting change, but no Platform sign-in or credential creation is needed for the local desktop route. A curated 30-question relevance study and large-scale performance work remain future evaluation, not evidence supplied by this small installation pilot.

## Practical limits

Daily scheduled backups remain on the same disk. An encrypted Drive snapshot has now
passed download/checksum/quarantine-restore verification. Drive uploads remain manual
by user choice; off-Mac recovery-key storage remains a user setup step; sleeping/logged-out machines can miss the 24-hour recovery target. Concurrent mutation detected during a snapshot fails that run rather than publishing a partial backup; inspect backup logs. Restores are quarantined and may contain historically deleted notes, requiring review before promotion.

Raw native read/search remains advisory. The current `recall_context` and
`capture_memory` tools enforce their documented scope, lifecycle, provenance and
write-validation contracts. Inspect payload-level failures even when transport success is reported. External edits converge asynchronously; avoid overlapping manual and agent changes. Reindexing at each launch may become costly as the vault grows. Hard-crash/power-loss safety and large-corpus performance remain untested.
