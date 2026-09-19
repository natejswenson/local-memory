# Red-team review: Obsidian memory hub

September 19, 2026. Three independent agents reviewed architecture, client integration, and local operations; the lead reconciled findings and revised the [implementation plan](../plans/2026-09-19-obsidian-memory-hub.md). This is a design review, not a runtime penetration test or a completed backend evaluation.

**Verdict: the original direction is reasonable, but the original plan was not ready to implement as written.** It deferred the required ChatGPT connection, mixed advisory tooling with guaranteed lifecycle behavior, and admitted real data before proving recovery. The revised plan is ready for an isolated feasibility pilot. Runtime gates remain open.

| Priority | Finding | Concrete failure | Revision | Remaining proof |
|---|---|---|---|---|
| P1 | ChatGPT access and authority were deferred | Local Codex works, but actual ChatGPT cannot reach or write the vault; adopting Cloud then creates a second authority | Actual ChatGPT/Codex synthetic round-trip is step 1; this Mac retains authority | Account/surface eligibility, transport and read/write behavior |
| P1 | Native tools do not enforce the proposed recall contract | A client omits status filters or frontmatter, retrieves a stale candidate, or requests a huge note | Choose advisory retrieval explicitly; remove hard filtering/byte-cap claims | Both clients' behavior on lifecycle and oversized-output fixtures |
| P1 | Source backup was absent from the real-data gate | Index rebuild succeeds but deleted Markdown is permanently missing | Independent backup and quarantined restoration precede real capture | Backup destination, schedule, retention and tested restore |
| P2 | Capture idempotency was underspecified | Lost reply triggers a new ID; simultaneous creates overwrite or duplicate | Retain a capture UUID across retries; add competing-write and kill-point fixtures | Atomic behavior of the pinned backend and selected ChatGPT path |
| P2 | Contradiction handling exceeded lexical retrieval | Old wording ranks highly; its differently worded correction is never read | Limit supported correction resolution to explicit keys/supersession links | Replacement outside initial top five must still be consulted |
| P2 | “All CLI chats” and ChatGPT workflow delivery were vague | Alternate configuration home or instruction override omits memory; ChatGPT has tools but no shared workflow | Inventory effective homes/profiles; separately deliver and test ChatGPT policy | Fresh/resumed/non-repository/worktree sessions and indirect prompts |
| P2 | Legacy migration was assumed necessary | An unused pilot triggers a large recovery/migration project; Ghostwriter gets two owners | Check status metadata first; defer source recovery/migration unless needed | Whether legacy data/integrations are active; per-consumer authority decision |
| P2 | Disconnected behavior was missing | Sleeping Mac yields invented empty-memory results or a false “remembered” acknowledgement | Explicit unavailable outcomes; no alternate writable store | Sleep, restart, expired/revoked authentication and interrupted-save tests |

**Why these findings are substantive**

The ChatGPT connection is not merely another configuration file. Basic Memory's published ChatGPT integration requires Basic Memory Cloud. Using it does not establish that the local Obsidian vault is connected. OpenAI documents Secure MCP Tunnel for private-server testing in developer mode; this offers a candidate route to retain the Mac as authority, subject to account/workspace eligibility. A tunnel also requires a running local service, and its development connection does not establish published-plugin distribution support. [Basic Memory ChatGPT](https://docs.basicmemory.com/integrations/chatgpt), [OpenAI connection testing](https://developers.openai.com/plugins/deploy/connect-chatgpt)

The native tool interface allows optional search filters, note reads without frontmatter by default, overwrite-enabled writes, and separate edit/delete operations. A prompt saying “active notes only” does not turn that interface into a policy engine. The revised plan deliberately accepts advisory behavior for trusted personal clients and measures it. Strict enforcement would require a distinct implementation decision. [Basic Memory tool reference](https://docs.basicmemory.com/reference/mcp-tools-reference)

The original five-hit retrieval limit could hide a correction. The concrete fixture is a previous “Use hashtags” note and an explicit replacement “Use plain text only”: searching for hashtags must not return the obsolete value just because the replacement does not match. Keyed lookup and explicit replacement links bound this problem without promising general semantic contradiction detection.

An ignored vault inside a code repository remains exposed to repository cleanup and has no inherent recovery. The user's chosen location is retained, but installation now requires cleanup exclusions and an independent backup. Restoring old files can reintroduce deleted or superseded notes; the restored vault must be reviewed before clients attach. Rebuilding an index is a separate test and cannot substitute for source restoration.

Two connected clients are not proof of universal session coverage. Effective instruction discovery can differ from a default global file, and connection availability does not guarantee automatic model use. The revised scope inventories actual configuration homes/profiles and tests workflow behavior separately. [Codex instruction discovery](https://learn.chatgpt.com/docs/agent-configuration/agents-md), [Codex MCP](https://learn.chatgpt.com/docs/extend/mcp?surface=cli)

**Scope reductions made to preserve simplicity**

- One writable vault on this Mac; no implicit cloud master or bidirectional sync.
- One existing engine and one shared workflow; no new general policy engine.
- Agents create independent notes; existing-note consolidation remains human-directed.
- Correction support covers explicit keys and replacement links; no general contradiction detector.
- Legacy migration is optional and evidence-driven; Ghostwriter is not automatically next.
- Native response budgets and lifecycle behavior are measured targets, not guaranteed server constraints.

These are explicit tradeoffs. Advisory retrieval may fail on unfamiliar cases even when fixtures pass. Direct filesystem access bypasses any application convention. Cross-client recall is only available while the necessary services and connection are available. If these limits are unacceptable, choose an enforcing interface or different authority before implementation rather than quietly adding complexity later.

**First executable proof**

Create one synthetic decision through a Codex CLI session. Retrieve it from actual ChatGPT, create a second independently identified note there, and retrieve that note in a fresh Codex session in another repository. Repeat with an indirect prompt and no pasted policy. Stop each client's actual dependency and verify that affected client reports unavailability without claiming a save. A tunnel outage should affect ChatGPT while local Codex may continue through its own process; test whole-Mac unavailability separately. Only then proceed to retry/concurrency and backup/restore work.

No runtime vulnerabilities or Basic Memory data-loss defects were demonstrated. The review identifies confirmed gaps in the plan and unverified behavior that must be tested. Only documentation changed.
