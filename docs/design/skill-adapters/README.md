# Skill adapter design index

Status: implemented in source; integration revision 3. Per-skill bindings default disabled. Inventory: all 22 top-level plugins in claude-skills.

Four priority candidates, seven optional advisory integrations, and eleven deferred skills. Optional adapters and enforced deferrals are implemented. No personal-data migration or automatic opt-in occurs.

Use the [shared contract](contract.md), [security review](security-review.md), [field policy](field-policy.md), [accuracy review](accuracy-review.md), and [machine-readable catalog](catalog.json) before any per-skill implementation. The hub owns the canonical designs; identical per-skill review copies live under each plugin’s `references/local-memory-design.md`. The catalog pins their SHA-256 digests and inspected skill source hashes.

## Assessment

| Skill | Recommendation | Design |
|---|---|---|
| appletv | Defer | [appletv](appletv.md) |
| bible-study | Optional advisory | [bible-study](bible-study.md) |
| brandreport | Defer | [brandreport](brandreport.md) |
| city-report | Optional advisory | [city-report](city-report.md) |
| devlog | Priority reader | [devlog](devlog.md) |
| eval | Defer | [eval](eval.md) |
| ghfactory | Optional advisory | [ghfactory](ghfactory.md) |
| ghostwriter | Priority owner bridge | [ghostwriter](ghostwriter.md) |
| ghostwriter-x | Priority owner bridge | [ghostwriter-x](ghostwriter-x.md) |
| github-stats | Defer | [github-stats](github-stats.md) |
| gmailtriage | Defer sensitive | [gmailtriage](gmailtriage.md) |
| issuecreator | Priority advisory | [issuecreator](issuecreator.md) |
| issueflow | Optional advisory | [issueflow](issueflow.md) |
| netwatch | Defer sensitive | [netwatch](netwatch.md) |
| pluginsync | Defer | [pluginsync](pluginsync.md) |
| press | Defer | [press](press.md) |
| release | Defer | [release](release.md) |
| resume | Optional advisory | [resume](resume.md) |
| shipflow | Defer | [shipflow](shipflow.md) |
| shipreport | Optional advisory | [shipreport](shipreport.md) |
| skillfactory | Optional advisory | [skillfactory](skillfactory.md) |
| skillhelp | Defer | [skillhelp](skillhelp.md) |

## Review scope

Inspected the root repository instructions, every shipped SKILL.md’s workflow/ownership landmarks, the current memory companion contracts, and selected persistence/validation implementation surfaces. This is an integration design assessment, not a complete code or privacy audit of every skill. No personal source files, real notes, mail, device captures or credential stores were used to construct examples.

## Implementation sequence

Start with the shared advisory contract and Issuecreator. Prove Ghostwriter backend parity with synthetic records before any owner-data move, then add the separately scoped X owner and Devlog reader. Optional integrations follow demonstrated use. The eleven deferred skills receive no runtime hook.

Each implementation change must preserve its existing baseline, add positive and negative synthetic adapter tests, and support both Claude and Codex. Desktop availability is capability-dependent; a shell bridge alone does not establish desktop support.

## Keeping the two repositories in sync

Contract identifier: `skill-memory-v1`. local-memory is canonical. For a design change, update the hub files and catalog digests, then update the matching claude-skills copies in the same review batch. Cross-repository PRs should name both source commits and the contract ID; pin the implemented protocol version rather than depending on matching branch names. Per-skill specs are not executable configuration.

See [current operations](../../skill-memory-operations.md) for the implemented protocol, setup and recovery. The original inspected source hashes are historical design provenance; they are not expected to match changed entrypoints after implementation.
