# Central activity in Obsidian

Central skill activity reporting is an optional local integration. The authoritative
journal is `vault/Activity/YYYY-MM/UUID.md`. Open **Home → Activity → Activity views**
for outcomes, published posts, failures/uncertainty, grouping by skill and tool calls.
**Activity/Coverage** reports the most recent source checks and hook execution.

## Supported sources

| Source | Capture | Local prerequisite |
| --- | --- | --- |
| Skills in configured clients | Concise outcome through `record_activity` | Explicit reporting opt-in and connected memory tools |
| LinkedIn and X Ghostwriter | Allowlisted local success-log adapters | Authorized source paths and optional sync job |
| Codex local tool calls | Metadata-only PostToolUse hook | Hook installation and host trust |
| Fitness | Existing owner reads/writes | Independently configured owner integration |
| Unconfigured or hosted clients | No implicit capture | Separately evaluated connection |

Inspect private `Activity/Coverage` and hook status for actual local coverage. Keep
personal publication counts, import dates, and host attestations out of public docs.

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

When installed, `com.local-memory-hub.activity-sync` runs at login
and every 300 seconds while the user session is available. It uses the hub's Python
for both synchronization and readiness checks. Sleeping/logged-out machines delay
updates. Config is `.runtime/activity-config.json`; setting `enabled` to false stops
both the importer and the hook from recording. Existing history is preserved.

The Codex hook lives in `~/.codex/hooks.json`. The installer preserves other hooks
and the existing `notify` configuration. New/changed hooks require review in `/hooks`.
Execution health is separate from trust and appears in `.runtime/general-memory/activity/hook-status.json` after a native
host invocation. Existing sessions may require restart. Hosted tools and some
specialized tool paths do not emit these local hook events.

Native image results can contain multi-megabyte data URLs. The hook accepts up
to 64 MiB of JSON in memory, extracts only the existing bounded metadata, and
discards input/output bodies before recording. A larger or malformed event still
leaves the original tool outcome untouched. `hook-status.json` carries a fixed
error code and processing stage on failure; `hook-last-failure.json` retains the
latest failure metadata after later successful calls, without storing payloads
or exception text. This avoids losing the reason for an intermittent warning.

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
metadata-only hooks, installer preservation, MCP and backup/restore. Verify live
imports, duplicate handling, fresh client access and native hook execution locally.
Keep operational receipts private; do not treat synthetic CI results as evidence
of a user's client round-trip or publisher history.

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
