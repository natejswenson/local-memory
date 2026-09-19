# ChatGPT desktop and Codex: subscription-only setup

Use the existing ChatGPT subscription. No OpenAI API key, API billing, Secure MCP Tunnel, or public endpoint is configured or required for the local MCP connection.

The [official MCP documentation](https://learn.chatgpt.com/docs/extend/mcp) says ChatGPT desktop, Codex CLI, and the IDE extension share `~/.codex/config.toml` on the same host. Hosted ChatGPT web does not read that configuration and is not connected by this setup. Developer mode was enabled in the web account with user approval, but that setting does not establish desktop MCP connectivity.

## Installed and enabled

The shared `local_memory_hub` registration now launches the **live vault** with the existing skill. The synthetic desktop/CLI round-trip below was completed before activation; it is retained as a repeatable acceptance procedure, not a pending user action. A fresh Codex CLI session has used this registration to create, read, and search a synthetic fixture. No server overrides were used for that verification.

Restart ChatGPT desktop, or restart its MCP connections in Settings → MCP servers, then start a new local conversation. Existing conversations may retain their old tool configuration. The protected desktop app cannot be controlled by this agent's computer automation, so the following native-tool test needs to run in that fresh conversation.

## Completed desktop round-trip prompt

For future synthetic revalidation, first select pilot mode with the installer. The original test prompt was:

> Test the installed local-memory synthetic pilot. Use only the native local_memory_hub MCP tools, with Basic Memory project local-memory. Do not use shell, filesystem, browser, or another memory service as a fallback. Search for the active synthetic note whose metadata key is hub.desktop-fixture and subject project is global. Read its full content and frontmatter, and report its verification value and identity. Then create one separate synthetic note in Inbox with a fresh UUID capture_id and that UUID in its title, overwrite=false, metadata project=global, status=active, key=hub.desktop-return, source=ChatGPT desktop synthetic round-trip. Its body should include the retrieved verification value and say this is a synthetic desktop return note. Inspect the semantic write result, read the new note back, and report its relative Markdown file path. If these native tools are unavailable, stop and say so.

Return the result and the return note's relative path to the installation conversation. Inspect actual native tool calls: plausible text, shell output, or a hand-written Markdown file does not establish desktop MCP access. Verify the returned value against the local fixture, check the persisted return note, and retrieve it from a fresh CLI session before activating personal capture.

## Completed activation procedure

The activation command records explicit operator attestation, plus a hash of the persisted pilot return note. It also requires passing engine and restored-index evidence. It is not an automated desktop test and must not be invoked before the actual desktop result is verified.

```sh
bin/memory-hub activate --desktop-verified --desktop-note 'Inbox/ACTUAL-RETURN-NOTE.md'
python3 scripts/install_codex.py --apply --mode live
bin/memory-hub doctor
```

Restart client MCP connections after switching modes. Live mode uses the original checkout's `vault/`; synthetic notes stay in `.runtime/pilot/vault/`. Confirm a fresh live startup, save/read a specifically authorized real memory, and check backup health before treating rollout as complete.

To disable the shared connection without deleting memories:

```sh
python3 scripts/install_codex.py --apply --mode disabled
```

Alternate `CODEX_HOME` values and explicit client/project overrides require separate installation checks. This does not promise every possible custom CLI configuration will inherit the default one.
