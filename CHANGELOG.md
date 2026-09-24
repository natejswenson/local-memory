# Changelog

## [0.1.0] - 2026-09-24

### Added

- Share editable Markdown memory between local MCP clients through an Obsidian
  hub, with scoped recall, source citations, freshness checks, and explicit
  capture authorization.
- Keep fitness and opted-in skill records with their owner tools while recording
  concise activity outcomes with distinct draft, failed, scheduled, and published
  states.
- Configure a private Atlas view, client integration, recovery workflows, and
  synthetic verification without committing personal notes or runtime state.
- Retain the separate SQLite memory implementation and its tested consumer
  contracts. Installing the hub does not implicitly migrate existing records.

### Release scope

This first source release includes the committed implementation and setup guides.
The Python hub and existing Node package both declare version 0.1.0. Host-specific
configuration, private vault contents, credentials, and uncommitted development
work are excluded. No npm or PyPI package is published by this release.
