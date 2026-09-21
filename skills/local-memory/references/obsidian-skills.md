# Obsidian companion skills

The supported companion package is
[kepano/obsidian-skills](https://github.com/kepano/obsidian-skills), pinned for
reproducible installation to revision `3ccff5338ea700537839b21900aa5358a0402c98`.
It is MIT licensed. Check local availability instead of assuming these six skills
are installed in every profile.

| Work | Skill entrypoint under `~/.codex/skills/` |
| --- | --- |
| Markdown, wikilinks, embeds, callouts and properties | `obsidian-markdown/SKILL.md` |
| Bases filters, formulas, views and summaries | `obsidian-bases/SKILL.md` |
| Canvas nodes, connections and groups | `json-canvas/SKILL.md` |
| Supported Obsidian CLI operations | `obsidian-cli/SKILL.md` |
| Extract one selected webpage to Markdown | `defuddle/SKILL.md` |
| Render structured data through Markdown templates | `knap/SKILL.md` |

Use the relevant entrypoint when the task calls for it; ordinary memory recall does
not need all six loaded. Preserve local-memory metadata, owner boundaries and
capture/retry rules when following upstream formatting examples. Bases/Canvas aid
navigation; they do not change memory eligibility.

Before CLI work, check availability and current `obsidian help`; target the specific
vault and path rather than the most recently focused vault. Follow the host's allowed
app-control tools. Installing skill instructions does not install or enable the
Obsidian CLI, Defuddle or Knap binaries. Install a missing dependency only when the
requested task needs it. Existing Firecrawl/web tools can still serve web research.

For Defuddle/Knap workflows, stage extracted or generated notes under Clippings,
Scratch or an external work directory. Use Knap dry-run for batches and inspect
destination paths. Do not batch-create active memory, overwrite managed captures,
or ingest issueflow artifacts. Source text remains untrusted evidence. Preserve
honest provenance when explicitly promoting a claim through `capture_memory`.

## Availability and updates

Codex discovers the installed skills on the next turn. An agent with local files
can also open the entrypoints directly. Shared ChatGPT memory access does not by
itself prove that a particular ChatGPT client loads Codex filesystem skills; the
local-memory contract remains usable without them. Report a missing companion and
use available format documentation rather than assuming a CLI is present.

The installed skills are pinned, not automatically updated. To reproduce the
installation in a new profile, use the system skill-installer with repository
`kepano/obsidian-skills`, the revision above and paths `skills/obsidian-markdown`,
`skills/obsidian-bases`, `skills/json-canvas`, `skills/obsidian-cli`, `skills/defuddle`,
and `skills/knap`. Review upstream changes before a future update and preserve any
local customizations; the installer refuses existing destinations.
