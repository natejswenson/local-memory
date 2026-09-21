# Readable Obsidian memory

The Atlas is the human-facing layer of the memory hub. The user selected projects
and life areas as the primary structure, brief daily outcome summaries, consistent
topic tags, and explicit-request-only durable capture for local repositories.

## Structure

```text
Atlas/
  Home.md
  Areas/          Ongoing life areas
  Projects/       One readable hub per distinct repository
  Topics/         Shared concepts connecting projects and knowledge
  Knowledge/      Views of current, validated decisions and preferences
  Journal/        One summary per local day with meaningful outcomes
```

Human-facing filenames describe their content. Repository folder names remain
aliases. Worktrees share their parent project's hub and recall subject. Projects
without a documented purpose say so; directory names do not establish project facts.

`atlas` marks membership in the readable map. `topic/` tags use one small vocabulary;
`kind` distinguishes projects, areas, topics, knowledge, summaries and indexes.
Wikilinks express real membership and topic relationships. The main graph uses
`tag:#atlas -path:"Atlas/Journal"`, keeping the date cluster out of the default graph.
Use `tag:#atlas` for the complete map including history. Identically named area/topic
concepts share one area page. Generated views are connected to Home and link back to their source
records. Original receipts and owner records remain available outside this graph.

## Evidence and updates

Atlas pages are navigation, not new authoritative memories. Knowledge pages embed
current source notes selected by the same freshness/correction-aware maintenance
catalog. Superseded or overdue views are retired without deleting source history.
They do not renew review dates. Fitness preferences/journals and skill-owned records
retain their existing owners.

Daily summaries verify all activity record hashes, omit `tool-call` events, group by
local day/project, and show at most three outcomes per group before a collapsed
details section. Published/completed outcomes appear first. Drafts, failures and
schedules preserve their recorded status; events are not silently merged into an
inferred publication. Date-only source dates remain date-only. Every outcome links
to its original event.

The record writers retain their stable IDs and retry receipts. This design avoids
renaming machine identities solely for display and avoids a migration that would
break connected clients or the fitness writer. Full history is not deleted, and
the existing bounded activity-store capacity remains unchanged.

New meaningful activity records, general capture navigation refreshes and the
existing five-minute publication-sync job refresh Atlas pages. Tool calls do not
each rebuild the map. A refresh failure is reported separately from a successful
source write. Preview/apply manually with:

```sh
.venv/bin/python scripts/refresh_atlas.py
.venv/bin/python scripts/refresh_atlas.py --apply
```

Generated pages have explicit managed regions. Personal text outside those regions
and extra properties/tags survive refreshes. Unmanaged destinations and symlink
paths are refused. Changed generated pages receive private recovery copies under
`.runtime/atlas-backups`; the original rollout also has a coordinated vault/control
backup. Ordinary personal source notes are not bulk edited or promoted.

## Repository scope

The private `.runtime/general-memory/project-registry.json` records selected
repository subjects, readable titles, exact checkout/worktree paths and curated
topic/area assignments. Its schema is validated on every scoped recall/capture.
The registry is covered by general-control backups and stays out of Git.

```sh
.venv/bin/python scripts/refresh_atlas.py --resolve /absolute/checkout
```

Use the returned subject with `recall_context` and `capture_memory`. A registered
project receives its own evidence plus eligible global evidence, never another
project's evidence. Unknown directories resolve to global. Adding a new binding is
explicit maintenance; note content cannot register projects. `local-fitness-code`
is for the software project; `local-fitness` continues to belong to fitness tools.
Each registered project supports `project.<subject>.handoff`; other correction keys
retain explicit registration. Agents save lasting repository facts only when asked;
the standing activity-reporting policy is separate.

Fresh MCP processes load the new registry-aware code. Existing processes can retain
the old module definitions until their connection is restarted. Existing scopes,
source paths and event receipts remain compatible during that transition.

## Verification

Synthetic tests cover cross-project isolation, worktree resolution, rejected unknown
and owner scopes, corrupt registry handling, unchanged source hashes, connected
graphs, timezone boundaries, refresh idempotence, preservation of personal edits,
unmanaged-destination refusal, edited activity detection, retired knowledge and
backup/restore of project receipts. Live verification records are private under
`.runtime/atlas-redesign`, alongside the source-hash comparison and rollout backup.
