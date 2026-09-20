# Memory workflow improvements

Skill outcomes and publication history now have a [central activity journal](central-activity.md),
including local publication-log synchronization, trusted Codex hooks and
Obsidian views. General preference recall excludes this historical namespace.

## Scoped recall with local semantic search

Use `recall_context(project="local-memory", subject="global"|"local-memory",
query=...)`, or supply exact `keys`. Every request reads current Markdown before
selection. Exact keys constrain the entire result. General recall excludes owner
namespaces (fitness and SkillMemory), templates, hidden/issueflow directories,
Scratch and Clippings. The selected subject also includes eligible global notes.

Weighted BM25 ignores common question words and requires meaningful query coverage.
When local semantic search is enabled, a local BGE-small embedding model reranks
lexical matches; if there are none, it discovers paraphrases. Reciprocal rank fusion
combines eligible rankings. This conservative policy was chosen after unrestricted
semantic candidates introduced irrelevant results in the synthetic evaluation.

The model uses Basic Memory's FastEmbed provider in offline-only mode. Provisioning
is an explicit download; inference does not require an API key or send notes to a
model service. Only revision-keyed vectors are cached in process memory. Fresh edits
replace vectors and deletions evict them. A model failure discloses
`semantic_unavailable` and returns bounded lexical evidence with partial status.
Disable hybrid retrieval by setting `.runtime/retrieval.json` mode to `lexical`.

```sh
.venv/bin/python scripts/setup_semantic.py --download
HF_HUB_OFFLINE=1 .venv/bin/python scripts/setup_semantic.py --enable
.venv/bin/python scripts/recall_context.py --subject local-memory --query 'deployment decision'
# Add --lexical for a baseline comparison.
```

Ranking never overrides lifecycle rules. Active notes require title, type, permalink,
project, status, source and capture_id. Corrections share a subject/key and one
complete explicit supersedes chain. Forks, cycles and broken chains are withheld.
Review dates apply to the terminal replacement; an expired replacement cannot revive
its predecessor. Candidates and archives cannot support ordinary advice. Semantic
search does not detect arbitrary contradictions.

Responses include provenance, path, identity and content revision. The default is
three whole notes (maximum five), within a 512–8192-byte compact JSON budget. MCP
wrappers add overhead. Malformed, oversized or unreadable managed files produce
explicit unavailability. Do not bypass it with raw search for advice. Scans are
bounded at 2000 Markdown files, 64 KiB each and 16 MiB aggregate; they are fresh but
not a cross-file atomic transaction with manual editors.

## Validated capture

`capture_memory` is the live general-memory write tool. Raw native `write_note` is
hidden and refused in live mode; it remains available only in the isolated synthetic
pilot for engine compatibility tests. Existing sessions need their MCP connection
restarted to discover the changed tool surface.

The capture tool generates paths, identity and timestamps, validates scope and
metadata, and publishes a complete immutable file. Candidate is the default. Each
request supplies one canonical UUID reused with identical arguments on retries.
Hash-only durable receipts live outside the vault in `.runtime/general-memory`.
Exact retries verify the current file. Changed requests, manual edits, deleted files
and pending receipts without a file require inspection; they are never blindly
recreated. Success requires `verified:true` and `created` or `already_created`.

Active corrections must supersede the current record under a registered key.
Register new keys together in `memory_hub/capture.py` and `docs/memory-conventions.md`.
Handoffs default to review in seven days and cannot exceed 30 days. Navigation refresh
runs after successful capture; a refresh failure reports that the note was saved.

```sh
.venv/bin/python scripts/capture_memory.py --interactive --apply
.venv/bin/python scripts/capture_memory.py --from-note 'Clippings/example.md' \
  --subject local-memory --source 'Verified original source'
# Review the preview, then repeat with --apply, its --capture-id and --expected-revision.
```

Selected-note promotion retains the original and checks its hash before creating a
managed copy. Do not promote whole unreviewed clippings. The older
`new_memory_note.py` remains a candidate-only drafting helper; use `capture_memory`
for durable retry receipts. Capture authorization still comes from the user/task,
not from a remembered claim or an external note.

## Obsidian workspace

```sh
.venv/bin/python scripts/install_vault_workspace.py          # preview
.venv/bin/python scripts/install_vault_workspace.py --apply
```

Home contains readable links and correction-aware navigation. Candidate review shows
missing metadata, conflicts, expired terminals and exact duplicate bodies. Managed
navigation is refreshed after capture and can be regenerated after manual edits.
The installer preserves custom text/templates and saves replaced files outside the
vault. It never removes personal notes.

`Memory views.base` provides live Candidates, Review due and Project history tables
using Obsidian's core Bases support. Views are navigation aids: the recall tool remains
the authority for resolved corrections and evidence eligibility. The live Base was
opened successfully in Obsidian. Decision, Preference and Handoff templates include
kind metadata. Scratch and Clippings accept freeform work and are excluded from
managed recall; promote only a selected revalidated claim.

## Verification and diagnostics

```sh
.venv/bin/python scripts/memory_health.py --details
.venv/bin/python scripts/evaluate_recall.py --mode lexical
HF_HUB_OFFLINE=1 .venv/bin/python scripts/evaluate_recall.py --mode hybrid
.venv/bin/python scripts/probe_recall.py  # initialized synthetic pilot only
.venv/bin/python scripts/benchmark_recall.py --sizes 100 500 1500
```

The evaluation contains 50 synthetic cases: wording changes, paraphrases, multi-note
questions, exact keys, irrelevant queries, corrections, expiry, scope and exclusion.
Both modes passed their 50 expected-contract cases. Against the same ideal evidence
labels, lexical recall was 0.926 and hybrid recall 1.000; both precision and abstention
accuracy were 1.000. These small fixture results are regression evidence, not a real
user relevance study or general search-quality guarantee. Threshold tuning used this
same suite; an independent held-out evaluation remains useful.

A fresh MCP pilot passed nine checks including current-file edits, correction
resolution, bounded replies, validated capture, exact retry, conflicting retry and retry after restart/reindex.
Unit tests cover capture interruption, deletion/edits, concurrent retries, malformed
metadata, owner boundaries and authenticated recovery. The health report returns
counts and repair reasons without bodies. `doctor` checks activation/configuration;
it does not prove a live cross-client round-trip. Startup still reindexes before
native reads. The earlier ChatGPT desktop round-trip is historical, user-attested
activation evidence; this update does not claim a new desktop test.

## Recovery

Version 3 coordinated backups include vault files plus skill and general control
JSON under writer locks. Version 1/2 archives remain readable. Restore always creates
a new quarantine, verifies hashes and never replaces live state. Preserve current
forgetting ledgers and capture receipts: restoring an old control snapshot can
resurrect forgotten/deleted material. Run `audit_memory_restore.py` for skill-ledger
reconciliation. Add `--current-general PATH --current-vault PATH` to compare
general receipts and current files before any promotion. The audit flags deleted or
edited files, pending/changed receipts and captures newer than the snapshot; it never
rewrites or promotes a restore. Native/manual notes without receipts require review. Fitness retains its owner-specific recovery process.

```sh
.venv/bin/python scripts/vault_backup.py backup --vault "$PWD/vault" \
  --skill-control "$PWD/.runtime/skill-memory" \
  --general-control "$PWD/.runtime/general-memory" --destination /absolute/private/backups
.venv/bin/python scripts/encrypted_backup.py create
.venv/bin/python scripts/encrypted_backup.py restore --archive /absolute/backup.fernet \
  --quarantine "$PWD/.runtime/new-restore-review"
```

The encrypted bundle contains the coordinated hub archive, a hash-matched fitness
owner archive when applicable, and recovery scripts/dependency locks. Fernet supplies
authenticated encryption. The default key is `.runtime/recovery-key.txt` (0600); save
it separately off this Mac, such as in a password manager. Never upload the key beside
the backup. Plaintext staging stays in private ignored runtime directories. Only the
`.fernet` artifact belongs in Google Drive.

A private Google Drive backup was uploaded, downloaded, verified by SHA-256 and
restored in quarantine. Private cloud receipts are in
`.runtime/drive-backup-receipt.json`. The existing daily local backup job now includes
both capture control stores and retains 14 snapshots. Unattended Drive upload is
not configured, per the user’s preference to keep uploads manual. A Drive snapshot alone does not establish ongoing backup freshness.

Backups include `.base`, `.canvas`, common attachments and configuration; indexes
remain rebuildable. Plain hub snapshot limits are 64 MiB per file and 256 MiB total.
The encrypted component budget is 300 MiB. Detected concurrent changes fail the run.
Avoid manual/fitness edits during snapshots; cross-owner operations are not one
atomic transaction. Sleeping/logged-out Macs may miss scheduled runs.

## Research behind the changes

- [Basic Memory semantic search](https://docs.basicmemory.com/concepts/semantic-search):
  local embeddings and keyword/vector retrieval; adapted here behind fresh-file scope
  and correction checks rather than delegating evidence authority to a stale index.
- [QMD](https://github.com/tobi/qmd): local BM25/vector retrieval and rank fusion;
  informed the ranking design without adding a second persistent content store.
- [Obsidian Bases](https://help.obsidian.md/bases): structured views over Markdown
  properties, used for review and history navigation.
- [Obsidian backup guidance](https://help.obsidian.md/backup): independent backups and
  recovery checks; implemented as an encrypted off-device archive plus restore test.

## Issueflow integration

The user selected Issueflow for this repository. Its private binding uses subject
`local-memory` and this repository root; the existing synthetic Issuecreator binding
remains separate and is not evidence of user preferences. The repository's AGENTS.md
documents the trusted subject mapping so the planner need not guess it.

Use the memory-capable installed Issueflow workflow (0.18.0 has the hook). Only its
planning worker recalls `project.design-rationale` and `project.known-constraint`
during investigation, then independently verifies current repository sources.
Its capture contract still requires an explicit user request, actual source file
hashes and a review date within 30 days. Enabling the binding does not invent facts,
copy older run artifacts or change an approved plan. Older Issueflow packages without
the hook continue their ordinary workflow; do not add memory to controller prompts.
