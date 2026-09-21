# Public source and private installation data

This repository contains reusable code, generic operating instructions, and
synthetic fixtures. It must not contain a personal profile or deployment diary.

| Public source | Private installation |
| --- | --- |
| Memory contracts, validators, generators | `vault/`: notes, activity, Atlas, Obsidian settings |
| Installer code and generic instructions | `.runtime/`: activation, tokens, logs, indexes, backups |
| Synthetic tests and reproducible test results | `.runtime/general-memory/project-registry.json`: repository inventory, paths, names, timezone, topics and areas |
| Integration protocols and public source references | `.runtime/general-memory/local-policy.json`: opt-ins, capture policy and host preferences |

General-control backups include the private JSON registry and policy. Filesystem
exclusion is not a backup and does not make `git clean -fdx` safe. Never clean or
reset the personal vault or private migration snapshots as build output.

## Before every commit

Review `git diff --cached`, not only the working-tree diff. Check for private
names, note excerpts, URLs, addresses, screenshots, account details, deployment
inventories and secrets. Inspect effective author and committer identities; use
a GitHub no-reply address. Then run:

```sh
python3 scripts/check_public_tree.py --check-identity
gitleaks git --staged --redact=100 --no-banner
git diff --cached --check
```

The index check rejects private storage paths even after `git add -f`, common
credential patterns, personal mailbox addresses and absolute home paths. The
same index check runs in the existing required repository-policy CI job through
`tests/test_public_repository.py`. It uses only Python's standard library.

To enable the local pre-commit guard, first inspect existing hooks and
`core.hooksPath`, then set `git config --local core.hooksPath .githooks` if that
does not replace another hook setup. The hook requires Python and Gitleaks.
Git hooks can be bypassed, and pattern scanners cannot recognize all personal
information. Manual review remains required. Do not upload scan reports to CI
artifacts when they could contain sensitive matches.

## Auditing previously published data

Audit all reachable refs with a redacted Gitleaks report saved under ignored
runtime storage. Inspect commit metadata and earlier file versions too. The
intentional synthetic password in the credential-rejection test is not a live
credential; review findings individually instead of broadly allowlisting tests.

Deleting a file or changing the current email does not remove earlier commits.
Rewriting published history changes commit IDs and requires coordinated approval.
Keep a private recovery copy, preview affected refs, and use expected-ref leases.
Copies, forks, PR refs and provider caches need separate follow-up; rewriting a
branch does not establish that every public copy was erased. Rotate an exposed
live credential even if a history cleanup is planned.
