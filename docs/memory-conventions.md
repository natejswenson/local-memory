# Memory conventions

Basic Memory's engine project is always `local-memory`; every tool call passes it explicitly. A note's `project` frontmatter is its subject context, not another engine project.

Registered subject contexts:

| Subject | Applies to |
|---|---|
| `global` | Explicit preferences useful across clients; each note's wording retains its original scope |
| `local-fitness` | Fitness questions in any client and the verified local-fitness repository/worktrees; use fitness-owned tools |
| `local-memory` | This repository (resolved from the installed skill), and its verified Git worktrees |

Additional local repositories selected by the user are registered privately in
`.runtime/general-memory/project-registry.json`, with readable titles and exact checkout
and worktree paths. Resolve with `.venv/bin/python scripts/refresh_atlas.py --resolve
/absolute/checkout`. Unknown repositories resolve to `global`; never infer identity
from similar folder names. The registry is outside the vault and included in control
backups. Private project names and paths are not committed to Git.

The bounded `recall_context` and `capture_memory` interfaces accept the default
subjects and validated registry subjects. `local-fitness` is always routed to its
owner; the explicitly registered `local-fitness-code` subject covers only software
decisions for that repository. Malformed registry state makes recall unavailable.
Subject selection is routing for trusted clients, not an access-control boundary.
Durable repository facts require an explicit capture request.
Routine skill outcomes continue to use the separate activity policy.

Registered correction keys:

| Key | Subject | Meaning |
|---|---|---|
| `preferences.memory-hub.openai-auth` | `global` | User's subscription-only constraint for this memory hub |
| `preferences.memory-hub.central-activity` | `global` | User's preference for every skill to report task outcomes to the central Obsidian journal |
| `project.local-memory.handoff` | `local-memory` | Short-lived, verified implementation state and next steps for this repository |

Synthetic keys `hub.desktop-fixture` and `hub.desktop-return` exist only in the isolated pilot. They are not user preferences. Add new real keys when capturing a new explicit kind of decision; preserve existing keys when correcting the same fact.

Each registered repository also supports `project.<subject>.handoff`. Other correction
keys still require explicit registration; arbitrary keys are not automatically accepted.

Validated capture enforces the key registry in `memory_hub/capture.py:KEYS`; update it
alongside this table when explicitly registering a new key. Ordinary note captures
may omit a key; explicit corrections require a registered key and the current
terminal identity. Live writes use `capture_memory`; raw native writes exist only
in the synthetic pilot for upstream engine compatibility tests.

`Scratch/` and `Clippings/` are unmanaged reference areas. They are excluded from
both bounded recall and Basic Memory indexing, including nested directories with
those names. Existing managed notes outside them remain strictly validated.

`Atlas/` is generated, readable navigation over source records and is also excluded
from AI evidence and Basic Memory indexing. It contains project/area/topic hubs,
current-knowledge views and daily summaries. Stable source identities and receipts
are not renamed. The main graph selects `tag:#atlas -path:"Atlas/Journal"`; human-facing filenames carry readable
titles. Topic tags aid filtering, and actual wikilinks express the relationships.

Stable note identity and `capture_id` identify each independent capture. `supersedes` links corrections to prior identities. Active conflicting notes without an explicit replacement remain a conflict; do not silently select the newest timestamp.

Fitness records are source-owned Markdown. The `fitness_memory` server exposes the
existing eight memory tools through one local writer. Basic Memory ignores
`Projects/local-fitness`; fitness recall validates live files rather than the
generic index. Updates use content handles and journal IDs, not generic correction
keys. See [fitness integration](fitness-migration-status.md).
