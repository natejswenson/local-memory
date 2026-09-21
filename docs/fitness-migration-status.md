# Fitness memory integration

The optional fitness integration provides a single-writer Markdown backend while
preserving the separate fitness owner's tools and legacy defaults. It does not
change model/provider selection or establish that a local migration has occurred.

The full `fitness` MCP registration supports current measurements, coaching prompts,
and owned memory. A memory-only registration cannot establish that current data is
unavailable. Restart existing client connections after changing the registration.

Synthetic tests cover namespace boundaries, authenticated writer operations,
migration validation, and recovery. Keep actual health records, migration counts,
source inventories, host status, tokens and activation receipts in private runtime
storage. Inspect those locally when verifying an installation; never publish them
as implementation status.

See [operations](fitness-memory-operations.md) for installation and rollback. The
operational contract is a loopback-only single writer and fitness subtree exclusion
from generic Basic Memory indexing. Historical design alternatives are not proof of
the current installation's state.
