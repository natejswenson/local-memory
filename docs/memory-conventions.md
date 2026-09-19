# Memory conventions

Basic Memory's engine project is always `local-memory`; every tool call passes it explicitly. A note's `project` frontmatter is its subject context, not another engine project.

Registered subject contexts:

| Subject | Applies to |
|---|---|
| `global` | Explicit preferences useful across clients; each note's wording retains its original scope |
| `local-fitness` | Fitness questions in any client and the verified local-fitness repository/worktrees; use fitness-owned tools |
| `local-memory` | This repository, `/path/to/local-memory`, and its verified Git worktrees |

Other repositories need an explicit subject selection/registration. Until then, recall only `global`; do not infer project identity from a similar directory name.

Registered correction keys:

| Key | Subject | Meaning |
|---|---|---|
| `preferences.memory-hub.openai-auth` | `global` | User's subscription-only constraint for this memory hub |

Synthetic keys `hub.desktop-fixture` and `hub.desktop-return` exist only in the isolated pilot. They are not user preferences. Add new real keys when capturing a new explicit kind of decision; preserve existing keys when correcting the same fact.

Stable note identity and `capture_id` identify each independent capture. `supersedes` links corrections to prior identities. Active conflicting notes without an explicit replacement remain a conflict; do not silently select the newest timestamp.

Fitness records are source-owned Markdown. The `fitness_memory` server exposes the
existing eight memory tools through one local writer. Basic Memory ignores
`Projects/local-fitness`; fitness recall validates live files rather than the
generic index. Updates use content handles and journal IDs, not generic correction
keys. See [fitness integration](fitness-migration-status.md).
