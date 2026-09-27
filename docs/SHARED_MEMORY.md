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

## Search: leave out superseded and archived notes

Setting: `search_exclude_inactive` (default `false`; env `BASIC_MEMORY_SEARCH_EXCLUDE_INACTIVE`).

```bash
bm config set search_exclude_inactive true
```

When it is on, `search_notes`, ChatGPT `search`, and `grep` (including `bm grep`) leave out
every note whose frontmatter `status` is `superseded` or `archived`, in any letter case. The
note's observations and relations drop out with it. Text, vector, and hybrid search all apply
it. A note with no `status`, or any other status, is unaffected.

- These still find a superseded or archived note: an exact permalink search
  (`search_type="permalink"` or a `memory://` URL), a status filter (`status="superseded"` or
  `metadata_filters={"status": ...}`), `read_note`, `cat`, `find`, `build_context`, and
  `recent_activity`.
- `include_inactive=true` on `search_notes` or `grep` includes them for that one call.
- You set the status. Nothing in this fork marks a note superseded: a `supersedes` key in
  frontmatter is stored like any other key and changes no other note.
- With the setting off, a search sends `exclude_statuses: null` and runs exactly the SQL
  upstream runs. The search API's `exclude_statuses` field takes any list of statuses; an API
  server that predates it ignores the field and returns unfiltered results.
