# Local memory hub

The canonical personal vault is `vault/` in the original checkout. It is user data,
not disposable build output. Never remove it with repository cleanup, reset, or
`git clean`. Never recursively ingest `.issueflow/` or `issueflow/` into memory.
Keep personal notes, runtime indexes, credentials and backups out of Git.

This is a public repository. Before every commit, review the actual staged diff
and commit identity for personal information, secrets, and local-only state.
Run `python3 scripts/check_public_tree.py` and a staged Gitleaks scan. Automated
checks supplement manual review; do not claim they prove all content is safe.
Reusable implementation, generic documentation, and synthetic fixtures belong in
Git. Host policy, project inventories, activation evidence, and personal taxonomy
belong under ignored `.runtime/` or `vault/`. See `docs/public-repository.md`.

The existing installed `local-memory` SQLite package is separate. Do not modify
its files or migrate its records implicitly. New infrastructure uses Basic Memory
and an isolated state directory; Markdown is authoritative.

Use synthetic notes for tests. Real capture stays disabled until the documented
ChatGPT/Codex round-trip and backup/restore gates pass. Configuration changes must
preserve unrelated existing host settings and instructions.

The default transport is shared local MCP for desktop and CLI clients. Do not
configure API billing, keys, tunnels, or public vault access implicitly. Read
installation-specific constraints from private host instructions and, when present,
`.runtime/general-memory/local-policy.json`; preserve them during maintenance.

Private fitness migration snapshots under `.runtime/fitness-migration/` contain
personal source data and backups. They are not disposable test output; never
index, commit, or remove them as part of routine cleanup.

## Obsidian authoring skills

The supported companion formats use https://github.com/kepano/obsidian-skills.
Use the installed `obsidian-markdown`, `obsidian-bases`, `json-canvas` or
`obsidian-cli` skill when the corresponding file format or operation is involved.
`defuddle` and `knap` support selected clipping and template workflows. Read
`skills/local-memory/references/obsidian-skills.md` for the pinned installation and
routing. These companions do not replace `recall_context`, `capture_memory` or
owner write tools. Stage bulk/extracted content in Scratch/Clippings; promotion to
managed memory requires the normal validation and authorization.

Independent recovery copies use encrypted archives at a separately configured
private destination. Uploads require installation-specific authorization; do not
install sync software or enable an unattended uploader implicitly. Keep recovery
keys separate from uploaded data.

## Issueflow memory in this repository

When host instructions or private local policy enable centralized skill activity,
follow the local-memory skill's
`references/activity.md`: record verified results and artifact links, with separate
draft/scheduled/published/failed/unknown states. This includes Issueflow outcomes
such as an opened PR, but does not ingest its run artifacts or put memory into its
controller/planning dispatch. Activity reporting does not change approval authority
or the explicit-capture rule for durable Issueflow project facts below.

Issueflow memory is opt-in. Read its binding from private local configuration;
never infer opt-in from this public repository. For enabled installations, use
the memory-capable Issueflow workflow and its `references/local-memory.md`
hook: only its planning worker recalls `project.design-rationale` and
`project.known-constraint` during investigation, then independently checks current
repository sources. Unknown/disabled/unavailable memory preserves ordinary investigation.
Never add memory to controller dispatch text, treat it as approval, refresh an
approved plan from memory, or ingest run artifacts. Capture still requires the
user's explicit request to remember a revalidated project fact.
