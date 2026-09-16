# Compatibility spike (2026-09-16)

Run `node scripts/compatibility.mjs` in an isolated temporary directory through
an actual host process tool. It tests the **loaded** SQLite version, transactions,
WAL, FULL sync, online backup plus integrity validation, FTS5, literal-token scan,
owner-only permissions, and executable invocation/restart. No user data is used.

## Selected package and runtime

An installable dependency-free npm package with a `local-memory` executable,
ES modules and Node's built-in `node:sqlite` binding. Minimum Node is 25.2.1;
**additionally the linked SQLite must be >=3.51.3**. Runtime capability checks
are mandatory: Node version alone does not establish SQLite safety. The observed
Homebrew Node 25.2.1 is dynamically linked to SQLite 3.53.1, despite build metadata
reporting 3.51.0. Stock Node builds carrying 3.51.0 are unsupported. CI's selected
runtime is pinned to Node 26.8.2 (published npm metadata inspected 2026-09-16).
The built-in binding version is the selected Node version; it has experimental
status in the observed minimum runtime. No native third-party binding is loaded.

| Environment | Observation | Support |
| --- | --- | --- |
| macOS arm64, Codex process tools, Homebrew Node 25.2.1 / loaded SQLite 3.53.1 | `codex-macos-arm64.json`; all probes passed | Supported local process/file access combination |
| Claude Code 2.0.76 executable | Discovery/version observed; in-host invocation not yet observed | Unverified, not claimed supported |
| Codex CLI 0.154.0 standalone session | Discovery/version observed; only current Codex process tools exercised | Unverified separately |
| Linux / Node 26.8.2 | Selected CI target; no hosted result yet | Unverified until CI passes |
| Windows | POSIX permission and lock implementation not applicable | Unsupported in v1 implementation |
| No process/file access, remote/network/synchronized storage | Cannot meet local durability contract | Unsupported |

This is a compatibility result, not evidence that memory behavior exists yet.
Storage defaults and executable distribution are implemented after this commit.
The fixture is reproducible without network access or credentials.
