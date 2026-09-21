# Central skill activity

The user opted all skill task outcomes into the central Obsidian journal on 2026-09-19.
This is ongoing authorization to record concise factual outcomes of authorized work,
including result links. It does not authorize performing new external actions.

## Agent workflow (all skills)

1. For a continuation or history question, call `recall_activity` with the relevant
   skill/subject, date range and optional keywords. Use `state: published` for posts
   actually recorded as published; do not infer publication from a draft or tool call.
2. Do the requested work using its normal skill and approvals.
3. At a meaningful result boundary, call `record_activity(request={...})`. This is
   expected for every skill task: artifact created, post published/scheduled, PR
   opened, research completed, settings changed, failure or cancellation. Record
   the outcome of a multi-step task rather than every conversational sentence.
4. Retain one UUID and the exact request for uncertain retries. Require `verified`
   and `recorded`/`already_recorded`. If recording fails, report that the work may
   have succeeded but its journal entry was not saved. Never rerun a post/send action
   merely because memory recording failed.

```json
{
  "event_id": "<generate one UUID>",
  "skill": "issueflow",
  "subject": "local-memory",
  "action": "create-pr",
  "state": "completed",
  "summary": "Opened a draft PR implementing the selected issue.",
  "occurred_at": "<actual ISO timestamp with timezone>",
  "source": "GitHub create-PR response, checked during this task",
  "source_id": "<returned PR URL or retained operation ID>",
  "artifacts": ["<returned URL without query parameters>"],
  "evidence_kind": "tool-result"
}
```

`state` is planned, drafted, scheduled, completed, published, failed, cancelled,
unknown or observed. `evidence_kind` is agent-report, source-log or tool-result.
`details` is optional (12 KiB max). Summary is 2 KiB max. Skill, subject and action
are lowercase slugs; activity subjects are labels, not new preference bindings.
Use `path:/absolute/file` for local artifacts or `vault:relative/path` for vault links.
Do not invent URLs, dates, source verification, outcomes, or skills you did not use.
An external success needs the actual result evidence. Partial/ambiguous outcomes
remain unknown; scheduling remains scheduled until a later publication confirmation.

## Automatic sources and hosts

LinkedIn Ghostwriter and X success logs are imported every five minutes while the
local user session is running. They use deterministic publication identities;
repeated sync is harmless and missing/deleted journal files are not resurrected.
Run `scripts/activity_memory.py sync --apply` with the hub Python after a publish
when immediate visibility is needed. For those publishers prefer this source-log
record over creating a duplicate manual published event. Drafts/failures can still
be recorded directly. Imports preserve the excerpt and result URL available in the
log; they do not claim to have copied the entire post or rechecked the platform.

Codex's PostToolUse hook records tool name, time, project label and observed status.
It drops tool inputs/outputs and transcripts. It skips memory tool calls to avoid
feedback loops. The host must trust the installed hook in `/hooks` before it runs.
A tool-call record is not a substitute for the meaningful skill outcome above.
A host without hooks can use the MCP outcome tool. Installing this does not prove
that every ChatGPT/Claude host is connected; disclose coverage in Activity/Coverage.

If the current client has an old tool list, reconnect. With authorized local shell
access, `scripts/activity_memory.py record` accepts the same JSON on stdin and
writes through the same validated store after a readiness check. This is the same
backend, not a fallback copy elsewhere. Hosted web remains unconnected.

## Boundaries and interpretation

Activity is stored in `vault/Activity/YYYY-MM/UUID.md`, with hash receipts under
`.runtime/general-memory/activity`. Do not edit generated events in place: a new
correction event can identify the prior event in source_id/details. No automatic
retention deletes history. Back up the vault and general control together.

The human-facing journal is `Atlas/Journal/Daily summaries.md`. It groups meaningful
outcomes by local day and project; tool-call receipts are omitted. Every outcome links
to its original record and preserves state. Topic tags use the shared `topic/` vocabulary;
project, area and topic wikilinks provide the graph edges. The `atlas` tag selects the
main graph, keeping detailed receipts out. New outcomes and the five-minute publisher
sync refresh these views. A failed view refresh never makes a saved event unsaved;
retry `scripts/refresh_atlas.py --apply` after repairing the reported source issue.

The default graph adds `-path:"Atlas/Journal"` to keep date clusters out of the main
knowledge view. Daily summaries remain connected and accessible through Home.

Recall verifies current file hashes, accepts filters and pagination, and bounds
whole-event output. Malformed/edited records are unavailable until reviewed. Query
with narrower filters if a record does not fit the budget. History remains separate
from current preferences and decisions; use `recall_context` and owner tools for
those. A past action never renews a preference or grants future permission.

Do not record credentials, access tokens, raw shell arguments/output, chat transcripts,
whole inbox messages, or issueflow run artifacts. Link to source systems and retain a
concise result. Fitness details stay in its existing vault namespace with its owner;
activity may link a confirmed outcome without duplicating the whole owner record.
Do not migrate legacy SQLite records or narrowly shared source preferences implicitly.
