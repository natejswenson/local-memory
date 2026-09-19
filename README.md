# Local memory hub

An Obsidian Markdown vault shared through Basic Memory's native MCP tools. Local ChatGPT desktop and Codex CLI can use the existing subscription without an OpenAI API key. New installations start in a synthetic pilot; see [activation evidence](docs/implementation-status.md) and the connection runbook before enabling personal capture.

- `vault/`: dedicated personal Obsidian vault, excluded from Git.
- `.runtime/pilot/vault/`: synthetic integration fixtures only.
- `.runtime/`: isolated engine configuration, rebuildable index, local test evidence.
- `skills/local-memory/`: small shared recall/capture workflow.

## Local setup

```sh
uv sync --locked
bin/memory-hub init
bin/memory-hub init --pilot
bin/memory-hub doctor
python3 scripts/install_codex.py             # preview
python3 scripts/install_codex.py --apply  # preserves the installed mode and other settings
```

The installer targets the active `CODEX_HOME` or `~/.codex`, installs the skill and bootstrap instructions, and saves originals in `local-memory-install-backup`. New default Codex CLI and local ChatGPT desktop sessions inherit the selected pilot/live configuration. Alternate homes, explicit overrides, and project instruction overrides need separate verification; already-running chats do not reload automatically.

For a synthetic client use the absolute `bin/memory-hub-pilot-mcp` launcher. It speaks stdio only. [ChatGPT connection runbook](docs/chatgpt-connection.md) records the subscription-only local desktop path; the earlier Secure MCP Tunnel proposal is superseded.

## Verification and recovery

```sh
.venv/bin/python -m unittest discover -s tests/hub -v
.venv/bin/python scripts/probe_engine.py
```

Run the engine probe with no other pilot clients. It creates synthetic notes and retains evidence under `.runtime/`. Failures are reported in JSON; the probe exits nonzero if a check fails.

Take snapshots while writers are idle. Choose a destination outside the vault; a copy on the same disk does not protect against disk loss.

```sh
python3 scripts/vault_backup.py backup --vault "$PWD/vault" --destination '/absolute/backup/directory'
python3 scripts/vault_backup.py restore --archive '/absolute/backup.zip' --quarantine '/absolute/new/review-directory'
```

Restores verify checksums and create a new quarantine directory. Review historical/deleted notes before any promotion; restore never merges into the live vault. The search index is rebuildable and is not backed up. `scripts/probe_recovery.py --synthetic-archive ARCHIVE --identifier NOTE_ID --marker EXPECTED_TEXT` tests index reconstruction and MCP retrieval from a synthetic snapshot; run it with `.venv/bin/python`. Daily launchd backups are installed with 14-snapshot retention; inspect `.runtime/live/backups/` for run results.

The legacy installed `local-memory` package remains separate. Do not run Git cleanup against ignored vault/runtime data. Move this checkout only after updating installed launcher paths and skill instructions.

## Fitness owner integration

Preferences and the coach journal have an optional single-writer Markdown backend,
with the full shared fitness MCP connection for coaching and Garmin queries. See [migration status](docs/fitness-migration-status.md)
and the [installation and recovery runbook](docs/fitness-memory-operations.md).
After installing the fitness integration, restart existing desktop/CLI sessions to
load the shared `fitness` tools. Fitness notes use owner reads rather than
the generic index.

## Existing memory package

The opt-in Node memory CLI remains available and unchanged. See the
[legacy package guide](docs/legacy-memory.md) for its installation and protocol.
It is a separate store; the Obsidian hub does not implicitly migrate it.

For this publication, changes land on `dev` before a PR promotes them to `main`.
The existing repository-policy and Node application checks remain in place.

See [CONTRIBUTING.md](CONTRIBUTING.md) for both test suites and publication policy.
