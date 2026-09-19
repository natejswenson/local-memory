# local-memory

An opt-in local JSON CLI for short preferences, confirmed facts and project
context. It provides scoped recall, explicit corrections, selected sharing,
bounded context and deletion-aware recovery. Data stays outside skill installs.

The dependency-free Node package includes a source-first ghostwriter companion
for `writing.hashtags` and a small second writing client. Both treat recalled
text as untrusted data; memory never grants authority for external actions.
No live source stores have been migrated or activated, and no package has been
published.

## Start here

- [Installation, protocol and management](operations.md)
- [Supported environments and observed probes](compatibility/README.md)
- [Durability, maintenance locks and crash recovery](recovery.md)
- [Validation matrix and measurements](validation.md)
- [Approved design](design/persistent-memory.md)

Use Node 26.8.2 for the pinned stock runtime. The minimum observed runtime is
Node 25.2.1 with a linked SQLite >=3.51.3; the CLI checks the loaded library.
The store is created only by explicit initialization. Basic checks:

```sh
npm ci --ignore-scripts
node scripts/compatibility.mjs
```

See [CONTRIBUTING.md](CONTRIBUTING.md#application-checks) for the full suite's
pinned completion-policy dependency and local test commands.

## Repository workflow

Contributions use GitHub Flow: short-lived branches open PRs directly to `main`.
CI retains `repository-policy` and adds `application`. Implementation PRs remain
draft until separately authorized. Live repository activation and credentials
remain the separate work in issue #1. A local pass does not establish hosted CI
or enforcement. See [CONTRIBUTING.md](CONTRIBUTING.md) before changing settings or
regenerating the merge automation.
