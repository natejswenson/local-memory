# Validation traceability

Input: the approved design at commit
`06e0181478dc57c3e028892005a5ff010e6ef776`, SHA-256
`8a3c23ae7fbef4e0466247713394a2a8fd24468b52d574d716531529f401ce0a`.
Tests use isolated synthetic stores and actual JSON CLI subprocesses. Capacity
fixtures seed internal tables solely to avoid exposing a bulk-import API.
Temporary fixture roots are canonicalized before constructing store, source and
project paths: macOS can expose its temporary directory through a symlink.
Runtime symlink rejection remains enforced; a storage test verifies rejection
both before initialization and after initializing through the canonical path.

| Pinned validation row | Automated evidence |
| --- | --- |
| Write, restart, recall | `v1-regression`: public CLI lifecycle; `scripts/host-smoke.mjs` |
| Upgrade/reinstall, rollback | `installation`: tarball install/uninstall leaves separate store; `adapters`: disable/re-enable retains source |
| Owner, selected recipient, unlisted, other project, projectless | `v1-regression`: public lifecycle; `adapters`: recipient freshness/project isolation |
| Forged caller/project, unapproved sharing | `limits`: forged identity; `adapters`: model scope rejected; `v1-regression`: unapproved grant |
| Duplicate and lost-response replay | `v1-regression`: canonical dedupe/receipt; `storage`: before/after commit; `adapters`: lost mirror acknowledgment |
| Conflicting duplicate, explicit/inferred both orders | `limits`: inferred/explicit order permutations; `v1-regression`: duplicate conflict |
| Equal-precedence cross-owner contradiction both orders | `v1-regression`: lexical group expansion reverse permutations |
| Nonmatching correction/competitor, both retrieval modes | `v1-regression`: group expansion in FTS5 and scan |
| Simultaneous writers and same-version update | `storage`: real concurrent subprocess writes/version conflict |
| Busy past deadline and bounded retry | `storage`: exclusive lock contention; adapter has one bounded jitter retry; a delayed worker tests the 4.8-second supervisor deadline |
| Kill before/after commit/acknowledgment | `storage`: before/after commit with receipt replay; `adapters`: lost acknowledgment |
| Review, expiry, clock advance | `storage`: injected clock, unchanged deadlines, foreground purge |
| Absent/missing/permissions/storage write failure | `v1-regression`: absent/no creation; `storage`: missing DB, unsafe modes/symlinks, unwritable backup; real SQLite `SQLITE_FULL` is induced with a temporary page limit; transactional rollback is verified |
| Corruption, invalid snapshot, missing journal | `storage`: corrupt DB retained/quarantined, missing journal, invalid manifest |
| Older/newer schema, migration failure | `storage`: schema versions, failed mandatory snapshot/migration rollback |
| Forget kill points and old backup restore | `v1-regression`: four deletion boundaries; `storage`: current ledger merged into an old snapshot |
| Pre-revocation restore, interruption before publication | `storage`: four restore boundaries; `v1-regression`: restored sharing reset |
| Unwritable backup and held WAL reader | `storage`: real POSIX permissions and held read transaction; no recalled content |
| FTS absent; oversized context/record | `storage`: drop FTS fixture; `v1-regression`/`limits`: budget and text bounds |
| 1,000 conflicts, mixed groups, 64/8192/63 budgets | `limits`: 1,000 groups in both modes; `v1-regression`: 63 rejected |
| Secrets and recalled injection | `v1-regression`: secret rejection and inert instruction text; `adapters`: explicit current-instruction override and untrusted envelope |
| Source succeeds/mirror fails; source fails/manual edit | `adapters`: failure points, source retention and revision invalidation for every recipient |
| Forget/restart/reconcile/disable/re-enable | `adapters` and self-contained `v1-regression` mirror suppression case |

Additional checks cover 10,000-record admission, content-free receipts, bounded
listing, three-snapshot retention, 70 MiB WAL admission with a held reader,
restoring a missing initialized DB, key precedence and broader confirmed types.
The same self-contained regression assertions are suitable for the controller's
base/fixed overlay. Existing repository and completion-policy assertions remain
unchanged.

## Reproduce

Follow the environment setup in [CONTRIBUTING.md](../CONTRIBUTING.md#application-checks).
The full Node suite, Python policy suite, actionlint and zizmor are required.
CI additionally runs the loaded-SQLite compatibility probe and benchmark with
pinned Node 26.8.2. A missing completion-consumer environment variable is a setup
failure, not a skip. Workflow refs were resolved using ghfactory; hosted CI is
reported separately by the implementation PR, never inferred from local tests.

## Measurements and limitations

[Observed 10,000-record run](compatibility/benchmark-macos-arm64.json): exact-key
and literal-query recall each 5/5 in both modes, ten timings per mode, end-to-end
p95 166 ms scan / 161 ms FTS5 on the observed Mac. Database/index size was
13,586,432 bytes, WAL zero after connections closed, and 1,000 content-free
journal entries used 118,784 bytes. These are synthetic measurements, not semantic
recall or personal-data demand estimates. The WAL-pressure test separately holds
a reader open and checks the 32/64 MiB admission thresholds.

No physical power-loss, hardware failure, Windows ACL, network filesystem,
no-process host, live migration or user-data pilot is claimed. Claude Code's
executable was found but its in-host smoke attempt exited without a structured
result; it is not a passing host. The current Codex process/file-access host
passed the synthetic adapter smoke. Standalone Codex CLI and hosted Linux CI
remain separate observations; consult the support matrix and PR checks.

The companion skills are explicitly invoked add-ons; they require no edits to
upstream ghostwriter. Automatic invocation inside the upstream distributed skill
is intentionally not activated here. Source stores, receipts, credentials and
publishing authority remain under their original owners.

## Observed local results (2026-09-16)

| Check | Observed result |
| --- | --- |
| Full Node suite, Homebrew Node 25.2.1 / SQLite 3.53.1 | 58 passed, zero failures; about 29 seconds |
| Regression with a symlink alias of the prepared temporary root | 13 passed; fixture paths canonicalized, runtime protections unchanged |
| Python repository policy | 9 passed |
| Workflow schema/security | actionlint clean; zizmor no findings |
| ghfactory CI ref/input validation | 5/5 action references resolved; current pins; actionlint/zizmor clean |
| Compatibility | Both the minimum observed runtime and stock Node 26.8.2 passed the loaded-library probe |
| Synthetic host adapter smoke | Current Codex process host passed; Claude attempt did not produce a passing result |

Controller base/fixed verification and hosted PR CI are independent subsequent
checks. No local log is presented as a controller verification receipt.
