# Restore the full coach outside the fitness repository

The reported Codex session `reported local coaching session` ran from
`local-memory`, so it inherited only the global eight-tool memory registration.
The full `fitness` server was project-local. Its replies accurately reported that
current metrics were unavailable, but the installation should have supplied those
tools. Operational data and the deployed application are healthy.

Replace the owned global `fitness_memory` registration with the existing full
`fitness` stdio server. Use the same server key as the project configuration so
project sessions do not gain duplicate memory tool aliases. Preserve all unrelated
settings and save the old config privately. Keep the vault backend unchanged.
Update the installer and shared skill so reinstallation cannot recreate the gap.

Verify a new client from `local-memory` with no inherited fitness environment:
48 tools, coach persona, coach/brief prompts, current daily snapshot, a populated
30-day RHR series, brief context, existing memory, and database coverage through
MCP. No model call, Garmin ingestion, email, or calendar mutation is needed to
check this connection. Add a regression that upgrades the old restricted config
and refuses to overwrite an unrelated pre-existing fitness server.
