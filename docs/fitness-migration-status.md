# Fitness memory implementation status

The production single-writer backend and full global coach connection are
implemented. The fitness adapter shipped through local-fitness PR #265. It keeps
legacy defaults for other installations and introduces no model/provider changes.

Validation includes 2,895 fitness tests with 95.23% coverage, 45 hub tests, the
16-check native MCP probe, same-machine performance checks, authenticated
host/container reads and writes, source/restore/reverse-export parity, and
preservation of journal allocation history. Personal inventories, original
configuration, migration manifests, health records, tokens, and detailed host
receipts remain private under ignored runtime directories. No production data is
included in this repository.

The original global eight-tool memory connection could not answer current Garmin
questions outside the fitness project. The installer now registers the full
`fitness` server under the same key as the project connection. A fresh client
verified all 48 stdio tools, coach/brief prompts, populated measurements, and
vault memory; the authenticated container endpoint was also verified. Existing
sessions must restart to load the changed registration. A fresh desktop UI round
trip for this later connection change is not separately attested.

See [operations](fitness-memory-operations.md) for installation and rollback.
Historical design documents describe explored alternatives; the operational
contract is the loopback-only single writer, full coach registration, and
fitness subtree exclusion from generic Basic Memory indexing.
