# local-memory

Repository foundation for local-memory. Application code has not been added yet.

Contributions use GitHub Flow: short-lived feature and maintenance branches open
pull requests directly to `main`. See [CONTRIBUTING.md](CONTRIBUTING.md) for the
required `repository-policy` check, merge process, and maintainer audit commands.

## Setup status

The committed files are the proposed policy and automation. Live activation and
validation are pending: the maintainer must provision `SHIPFLOW_AUTOMERGE_PAT`,
verify hosted CI, apply the reviewed settings, and complete a validation PR.
The setup PR remains draft. Draft and fork PRs intentionally skip generated
auto-merge; unavailable configured credentials leave automation inactive.
Local test success does not establish that GitHub currently enforces this policy.

The workflow uses reviewed unreleased generator source, pinned to an immutable
commit. See [maintainer source reproduction](CONTRIBUTING.md#maintainer-generator-source-unreleased)
before regenerating or activating the setup.
