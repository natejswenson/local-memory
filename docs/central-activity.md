# Central activity in Obsidian

The user selected central skill activity reporting on 2026-09-19. The authoritative
journal is `vault/Activity/YYYY-MM/UUID.md`. Open **Home → Activity → Activity views**
for outcomes, published posts, failures/uncertainty, grouping by skill and tool calls.
**Activity/Coverage** reports the most recent source checks and hook execution.

## What is connected

| Source | Capture | Current coverage |
| --- | --- | --- |
| All skills in configured Codex sessions | Concise outcome through `record_activity` | Global instructions, skill routing and MCP tools installed; existing sessions must reconnect |
| LinkedIn Ghostwriter | Local success-log import every five minutes | 31 historical records imported |
| X Ghostwriter | Local success-log import every five minutes | 9 historical records imported |
| Codex local tool calls | PostToolUse metadata hook | Installed; user reported trusting it; first native host event not yet observed during setup |
| Fitness | Existing owner reads/writes | Preferences and journal already in `Projects/local-fitness` |
| Hosted ChatGPT web and other unconfigured hosts | None | No transport or hook silently installed |

The two publication adapters preserve the available excerpt, date and result URL.
They do not contain full post bodies and do not re-fetch external platforms. Drafts,
schedules, failures and published events are distinct. A tool invocation never proves
a business action succeeded. Publishing still follows its original skill workflow.

Every connected skill should recall relevant activity when continuing work, then
record the result and artifact links at a meaningful task boundary. This is an agent
instruction, not proof that every future agent complies. Local source adapters add
automation for the two known publishing logs. A new application needs an explicit
adapter or must use the common tool; there is no universal background recorder.

## Implementation and operations

`record_activity(request)` validates a retained UUID, skill, subject, action, state,
summary, source, source ID and time. It publishes an immutable note, verifies the
readback and stores hash receipts outside the vault. Identical retries do not duplicate
events. Changed requests, edited files and deleted records require review rather
than recreation. `recall_activity` verifies current hashes and supports skill/subject,
state, date, keyword and pagination filters. History is excluded from general
preference/decision recall. Detailed agent guidance is in
[the activity contract](../skills/local-memory/references/activity.md).

```sh
.venv/bin/python scripts/activity_memory.py sync          # preview only
.venv/bin/python scripts/activity_memory.py sync --apply
.venv/bin/python scripts/activity_memory.py status
.venv/bin/python scripts/activity_memory.py recall --skill ghostwriter --state published --limit 3
.venv/bin/python scripts/install_activity.py              # preview host integration
```

The installed launch agent is `com.local-memory-hub.activity-sync`. It runs at login
and every 300 seconds while the user session is available. It uses the hub's Python
for both synchronization and readiness checks. Sleeping/logged-out machines delay
updates. Config is `.runtime/activity-config.json`; setting `enabled` to false stops
both the importer and the hook from recording. Existing history is preserved.

The Codex hook lives in `~/.codex/hooks.json`. The installer preserves other hooks
and the existing `notify` configuration. New/changed hooks require review in `/hooks`.
The user reported completing that review during setup; execution health is separate
and appears in `.runtime/general-memory/activity/hook-status.json` after a native
host invocation. Existing sessions may require restart. Hosted tools and some
specialized tool paths do not emit these local hook events.

The hook retains tool name, time, a project label, stable event identity and observed
status. It does not retain arguments, output bodies or transcripts. The journal
rejects common credential patterns but is not a complete secret classifier: callers
must supply concise redacted outcomes. No recursive transcript, mailbox or Issueflow
artifact scan is configured. Optional skill-owned preferences retain their bindings
and owner contracts; the activity journal does not implicitly enable those stores.

Activity recall currently bounds scans to 10,000 events / 64 MiB and output to
16 KiB maximum. At capacity it reports unavailable; it never silently prunes history.
Tool-call volume will eventually require a larger indexed/paged archive design.
No automatic retention or deletion was introduced.

## Recovery and verification

Activity receipts share the general-memory writer lock and backup control directory.
Coordinated and encrypted backups include notes and receipts. Restore auditing checks
activity receipts against current files, flagging later edits/deletions and events
newer than a snapshot. Restore is quarantined and never promotes historical state.
Google Drive uploads remain manual. See [recovery](hub-recovery.md).

Synthetic tests cover duplicate/concurrent retries, interrupted writes, deletion,
manual edits, scoped/bounded recall, rejected secrets and paths, source import,
metadata-only hooks, installer preservation, MCP and backup/restore. Live publication
import and a real launchd repeat were verified: 40 records, zero duplicates/rejections.
A fresh stdio MCP client verifies the exposed tools and publication retrieval.
This does not claim a new ChatGPT desktop round-trip or a native hook event before
one has actually appeared in hook health.

## Research and design choices

These are adaptations of documented patterns, not installations of the other systems:

- [Basic Memory observations and relations](https://docs.basicmemory.com/concepts/observations-and-relations)
  provides structured observations within readable Markdown. We use Markdown properties,
  attributed event details and result references while keeping existing owner stores.
- [OpenClaw bundled hooks](https://docs.openclaw.ai/automation/hooks/bundled-hooks)
  demonstrates event-driven memory capture and a separate command log. We apply that
  separation to meaningful skill outcomes and minimal tool-call records.
- [Graphiti](https://github.com/getzep/graphiti) retains temporal knowledge with
  provenance. That informed retaining occurrence/recording times and historical
  events separately from current preferences; no graph database or LLM extraction
  dependency was added.
- [Codex hooks](https://learn.chatgpt.com/docs/hooks) documents PostToolUse, background
  handlers, tool coverage and exact-definition trust. We use the native hook contract
  and preserve its user trust requirement. It is not an all-application event bus.
- [Kepano's Obsidian skills](https://github.com/kepano/obsidian-skills) and
  [Obsidian Bases](https://help.obsidian.md/bases) supply the format/workspace patterns
  for browsing the central journal. The installed companion skills remain linked from
  local-memory's instructions.
