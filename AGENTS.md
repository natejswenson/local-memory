# Local memory hub

The canonical personal vault is `vault/` in the original checkout. It is user data,
not disposable build output. Never remove it with repository cleanup, reset, or
`git clean`. Never recursively ingest `.issueflow/` or `issueflow/` into memory.
Keep personal notes, runtime indexes, credentials and backups out of Git.

The existing installed `local-memory` SQLite package is separate. Do not modify
its files or migrate its records implicitly. New infrastructure uses Basic Memory
and an isolated state directory; Markdown is authoritative.

Use synthetic notes for tests. Real capture stays disabled until the documented
ChatGPT/Codex round-trip and backup/restore gates pass. Configuration changes must
preserve unrelated existing host settings and instructions.

User constraint: use the existing OpenAI subscription only. Do not request or
configure OpenAI API keys, API billing, or Secure MCP Tunnel. Prefer the shared
local MCP configuration for ChatGPT desktop and Codex CLI. Hosted ChatGPT web
requires a separately evaluated transport; do not silently expose the vault.

Private fitness migration snapshots under `.runtime/fitness-migration/` contain
personal source data and backups. They are not disposable test output; never
index, commit, or remove them as part of routine cleanup.

## Obsidian authoring skills

The user selected https://github.com/kepano/obsidian-skills for work on this hub.
Use the installed `obsidian-markdown`, `obsidian-bases`, `json-canvas` or
`obsidian-cli` skill when the corresponding file format or operation is involved.
`defuddle` and `knap` support selected clipping and template workflows. Read
`skills/local-memory/references/obsidian-skills.md` for the pinned installation and
routing. These companions do not replace `recall_context`, `capture_memory` or
owner write tools. Stage bulk/extracted content in Scratch/Clippings; promotion to
managed memory requires the normal validation and authorization.

Independent recovery copies use encrypted archives in private Google Drive.
The user selected manual Drive uploads; do not install Drive desktop or enable an
unattended uploader implicitly. Keep the recovery key separate from uploaded data.

## Issueflow memory in this repository

All skill task outcomes now belong in the central Obsidian activity journal under
the user's explicit centralization request. Follow the local-memory skill's
`references/activity.md`: record verified results and artifact links, with separate
draft/scheduled/published/failed/unknown states. This includes Issueflow outcomes
such as an opened PR, but does not ingest its run artifacts or put memory into its
controller/planning dispatch. Activity reporting does not change approval authority
or the explicit-capture rule for durable Issueflow project facts below.

The user opted Issueflow into shared-vault memory for this repository. Its private
binding is `skill: issueflow`, `subject: local-memory`, rooted at this checkout.
Use the installed memory-capable Issueflow workflow and its `references/local-memory.md`
hook: only its planning worker recalls `project.design-rationale` and
`project.known-constraint` during investigation, then independently checks current
repository sources. Unknown/disabled/unavailable memory preserves ordinary investigation.
Never add memory to controller dispatch text, treat it as approval, refresh an
approved plan from memory, or ingest run artifacts. Capture still requires the
user's explicit request to remember a revalidated project fact.
