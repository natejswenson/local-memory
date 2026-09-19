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
