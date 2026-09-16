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
| Claude Code 2.0.76 | In-host smoke attempt exited 1 without a structured result; `claude-host.json` | Unavailable in tested sandbox; not claimed supported |
| Codex CLI 0.154.0 standalone session | Discovery/version observed; only current Codex process tools exercised | Unverified separately |
| macOS arm64 / stock Node 26.8.2 | `node-26.8.2-macos-arm64.json`; loaded SQLite 3.53.4, probe passed | Supported runtime on the tested local host |
| Linux / Node 26.8.2 | Selected CI target; no hosted result yet | Unverified until CI passes |
| Windows | POSIX permission and lock implementation not applicable | Unsupported in v1 implementation |
| No process/file access, remote/network/synchronized storage | Cannot meet local durability contract | Unsupported |

The initial probe was committed as `c4c3921` before core implementation. Later
runtime and adapter evidence is recorded separately. `node scripts/host-smoke.mjs`
passed through the current Codex process tools and tests real source-first capture,
process restart, recall and forget. The tarball installation test validates
executable discovery and data persistence across uninstall. No personal data was
used. The synthetic fixtures run without network access or credentials.
