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

## Brief

`get_brief(project, token_budget)` and `memory://_brief/{project}` return a bounded
orientation for clients that do not run session hooks. `bm brief` prints the same text.

Settings (env vars use the `BASIC_MEMORY_` prefix):

- `brief_state_note` (default `project/state`) — included when the note exists
- `brief_profile_note` (default `me/profile`) — optional excerpt when the note exists;
  missing notes are omitted with no error text
- `brief_inbox_folder` (default `inbox`) — top-level markdown files counted in the brief
- `brief_decision_days` (default `14`) — decision note titles listed by search
- `brief_token_budget` (default `1500`) — rough character budget (`len / 4`); later
  sections drop first
- `brief_refresh_hours` (default `24`) — minimum time between `bm brief` deliveries for
  the same `--conversation-id` (use `--force` to override)

Delivery timestamps for `--conversation-id` are stored in
`<project>/.basic-memory/brief-delivery.json`. Pass `--delivery-store` to override the path.
This PR does not install SessionStart hooks; use `bm setup` when that lands in the stack.
