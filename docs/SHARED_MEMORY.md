# Shared memory (PelumiAlesh fork)

This fork of Basic Memory serves one memory folder to several AI clients on one Mac: Cursor,
Claude Code, ChatGPT, and Grok Bot. The folder is an Obsidian vault (default
`~/Documents/AI Memory`) that already has an `inbox/` folder written by the owner's own launchd
jobs.

Memory content stays on the machine. No feature in this fork sends note content to a remote.

This page describes only what the fork adds to upstream Basic Memory. Each section names the
setting that controls the feature and its default.

## Fork version and updates

Builds from this repository carry a PEP 440 local version label, for example
`0.23.2+pelumi.1`. Both `basic-memory --version` and the installed package metadata report it:

```bash
uv tool install --prerelease=allow \
  "basic-memory @ git+https://github.com/PelumiAlesh/basic-memory@main"
basic-memory --version        # Basic Memory version: 0.23.2+pelumi.1
```

The version comes from `__version__` in `src/basic_memory/__init__.py` (hatch reads it; see
`[tool.hatch.version]` in `pyproject.toml`). Upstream derives its version from git release tags,
which the fork does not have. To bump the fork, edit that one string. When an upstream release
changes it, resolve the merge by keeping the upstream release and the fork label, for example
`0.23.3+pelumi.1`.

Automatic updates never touch a fork build. The periodic CLI check, the background check in
stdio `basic-memory mcp`, and `bm update` all compare against the upstream release on PyPI or the
Homebrew tap. Acting on that answer would install upstream code (Homebrew, pip) or re-fetch
whatever the fork branch holds at that moment (`uv tool upgrade` on a git install re-resolves the
git URL). On a `+pelumi` build they stop before any network call and print the fork's own
reinstall command. `bm update --force` runs the upstream update path on purpose.

## Provenance: which app wrote a note

Setting: `record_provenance` (default `true`; env `BASIC_MEMORY_RECORD_PROVENANCE`).

When an app names itself in MCP clientInfo, `write_note` and `edit_note` add three
frontmatter keys:

```yaml
bm_source_client: cursor                     # the app that wrote the note last
bm_updated: '2026-09-27T14:04:05+00:00'      # when it did, in UTC
bm_created_by_client: cursor                 # the app that wrote it first
```

- The keys are namespaced. Your own `updated`, `created`, and `modified` keys are never
  written. A stamped edit replaces only the `bm_*` lines, so every other frontmatter line keeps
  its exact bytes. An overwrite (`write_note` on an existing note) keeps your values, but
  upstream Basic Memory re-serializes the whole frontmatter block on overwrite, so a value like
  `2024-03-01T09:30:00Z` can come back as `2024-03-01 09:30:00+00:00`.
- `bm_created_by_client` is set only when the write creates the note. MCP and API writes keep
  the value a note already has, and a note that never had one (for example, one you wrote in
  Obsidian) does not gain one when an app edits it. Edit the file directly to change it.
- Writes from apps that send no clientInfo, and all writes while the setting is off, are the
  same as upstream: no `bm_*` keys.
- Slugs: `cursor-vscode` and `cursor` become `cursor`; `claude-code` stays `claude-code`;
  `claude-ai` becomes `claude`; `openai-mcp` (ChatGPT) becomes `chatgpt`; `codex-mcp-client`
  becomes `codex`; `grok` and `grok-bot` become `grok`. Names match exactly. Any other name
  becomes its own lowercase slug (`My Bot` is `my-bot`), so a lookalike such as
  `cursor-attacker` is recorded as itself, not as `cursor`.
- clientInfo is whatever the app says about itself. Provenance is an audit label, not
  authentication: nothing is allowed or denied on it.
- `read_note` shows the keys in the note's frontmatter (text output) and in `frontmatter`
  (JSON output). Search does not print them on each hit, but you can filter on them, for
  example `search_notes(metadata_filters={"bm_source_client": "chatgpt"})`.
