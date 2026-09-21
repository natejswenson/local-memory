# Implementation status

This page describes reusable capabilities, not a particular user's installation.
Keep activation attestations, migration inventories, live source counts, host
health, and backup receipts in private runtime storage.

## Implemented capabilities

- Isolated Basic Memory configuration and a guarded local MCP launcher.
- Fresh-Markdown scoped recall, explicit corrections, bounded responses, and
  optional offline semantic ranking.
- Validated capture with immutable identity, retry receipts, and candidate review.
- Source-attributed activity reporting, allowlisted publication-log imports, and
  optional metadata-only host hooks.
- An Obsidian Atlas driven by private repository and presentation configuration.
- Source-owned fitness and optional skill integrations with separate namespaces.
- Coordinated local backups, encrypted recovery bundles, and quarantine audits.

## Verify a local installation

Run `bin/memory-hub doctor` to distinguish disabled, synthetic-pilot, and activated
personal memory. Verify a real client round-trip and backup/restore gates before
activation. Tool availability alone does not prove that the current desktop chat
has loaded the server. Existing connections must restart after code/tool changes.

Use the private activity coverage view, writer health, and configured launch-job
status for current integration coverage. Treat an unavailable store as unavailable,
not empty. Public documentation is never evidence about personal memories or host
readiness. Hosted web transport is a separate, explicit deployment decision.

## Validation and limits

`tests/hub` covers synthetic installation, owner boundaries, capture/recall,
activity, Atlas, backups, and restore behavior. CI provides the result for each
reviewed commit. Optional engine and fitness tests require their documented local
dependencies. Do not substitute a synthetic test for a real client's activation
attestation or claim that a one-time restore proves ongoing backup freshness.

Keep the legacy SQLite package and state separate. Markdown remains authoritative
for the hub; indexes are rebuildable. Never sweep operational worktrees or run
artifacts into memory. Manual editor operations and owner-specific writers are not
one filesystem-wide transaction; avoid overlapping edits and snapshots.

See [workflow details](memory-improvements.md), [Atlas](atlas.md),
[activity](central-activity.md), [recovery](hub-recovery.md), and
[public/private boundaries](public-repository.md).
