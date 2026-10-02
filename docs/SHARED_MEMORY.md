# Shared memory (PelumiAlesh fork)

This fork of Basic Memory serves one memory folder to several AI clients on one Mac: Cursor,
Claude Code, ChatGPT, and Grok Bot. The folder is an Obsidian vault (default
`~/Documents/AI Memory`) that already has an `inbox/` folder written by the owner's own launchd
jobs.

Fork features write only on this machine: the vault, `.bm-history/`, `.bm-logs/`, and
`~/.basic-memory/`. They do not open a connection to upload note bodies. `bm setup`
puts `BASIC_MEMORY_NO_PROMOS=1` and `BASIC_MEMORY_FORCE_LOCAL=1` on every MCP
server entry it writes and on the launchd agent, sets `logfire_enabled` and
`logfire_send_to_logfire` to false, and sets `cloud_promo_opt_out` so the CLI
promo panel does not call Umami. `analytics.track()` also returns before any
request when that flag is set or a fork setup manifest exists. Setup refuses
to run while a cloud API key, saved OAuth tokens, a default workspace, or any
cloud-mode project is configured.
`--uninstall` restores the previous config and those MCP files, and removes the
launchd agent. Upstream `basic-memory cloud push`, `cloud sync`, `cloud bisync`,
and `bm cloud login` still talk to the network if you run them. A terminal `bm`
you start yourself does not inherit the MCP env; the promo panel stays off because
of `cloud_promo_opt_out`. Logfire spans, when you turn them back on, do not attach
note bodies or search text. A client you connect (ChatGPT, for example) receives
whatever tool result you asked it to fetch. Semantic search can download an
embedding model once.

This page describes only what the fork adds to upstream Basic Memory. Each section names the
setting that controls the feature and its default.

## Fork version and updates

Builds from this repository carry a PEP 440 local version label, for example
`0.23.2+pelumi.3`. Both `basic-memory --version` and the installed package metadata report it:

```bash
uv tool install --prerelease=allow --reinstall \
  "basic-memory @ git+https://github.com/PelumiAlesh/basic-memory@cursor/v2-stack-integrated-7b2f"
basic-memory --version        # Basic Memory version: 0.23.2+pelumi.3
```

The version comes from `__version__` in `src/basic_memory/__init__.py` (hatch reads it; see
`[tool.hatch.version]` in `pyproject.toml`). Upstream derives its version from git release tags,
which the fork does not have. To bump the fork, edit that one string. When an upstream release
changes it, resolve the merge by keeping the upstream release and the fork label, for example
`0.24.0+pelumi.1`. This tree contains the unreleased v0.24.0 changes, but the public version
stays `0.23.2` until that release is tagged: the Claude plugin's `basic-memory>=` floor cannot
name a version that is not on PyPI. The local label sorts above PyPI 0.23.2, so install this
branch on purpose. Do not `uv tool upgrade` against PyPI.

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
  written. A stamped edit that changes only the `bm_*` keys replaces only those lines, so every
  other frontmatter line keeps its exact bytes. An overwrite (`write_note` on an existing note)
  keeps your values, but upstream Basic Memory re-serializes the whole frontmatter block on
  overwrite, so a value like `2024-03-01T09:30:00Z` can come back as
  `2024-03-01 09:30:00+00:00`.
- Upstream `created_by` and `updated_by` are a different record: the person or agent, stamped
  only when the runtime authenticated one (cloud writes such as `<member> via <key name>`).
  A local install supplies no author, so those keys are ordinary frontmatter and a value you
  typed by hand is left alone. The fork does not copy the app slug into them. `bm_source_client`
  is the app that wrote last, `bm_created_by_client` is the app that wrote first, and
  `bm_updated` is when that app stamp was written. None of those three is something
  `created_by` / `updated_by` store.
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

## HTTP transport: bearer token required

Stdio (`basic-memory mcp` with no `--transport`) is unchanged and needs no token. The HTTP
transports (`--transport streamable-http` and `--transport sse`) listen on a TCP port, so the
fork puts a bearer-token gate in front of them.

| Setting | Default | Env |
| --- | --- | --- |
| `mcp_http_host` | `127.0.0.1` | `BASIC_MEMORY_MCP_HTTP_HOST` |
| `mcp_http_token` | not set | `BASIC_MEMORY_MCP_HTTP_TOKEN` |
| `mcp_http_client_tokens` | `{}` | `BASIC_MEMORY_MCP_HTTP_CLIENT_TOKENS` (JSON object) |
| `mcp_http_allowed_hosts` | `[]` | `BASIC_MEMORY_MCP_HTTP_ALLOWED_HOSTS` (JSON list) |
| `mcp_http_allowed_origins` | `[]` | `BASIC_MEMORY_MCP_HTTP_ALLOWED_ORIGINS` (JSON list) |

- Without a token the server does not start. `basic-memory mcp --transport streamable-http`
  exits with status 1 and says how to set one. A token must be at least 16 characters:

  ```bash
  python3 -c 'import secrets; print(secrets.token_urlsafe(32))'
  ```

- Every HTTP request and WebSocket must send `Authorization: Bearer <token>`. Anything else gets
  401 with `WWW-Authenticate: Bearer realm="basic-memory"`. The one exception is exactly
  `/.well-known/oauth-protected-resource`, which answers 404 without a token. There is no OAuth
  server, and the 404 tells an MCP client that probes the path to use the header it was
  configured with.
- A path with a `..` segment gets 400 before routing, however it is percent-encoded.
- The server binds `127.0.0.1` unless `--host` or `mcp_http_host` says otherwise. A wider bind
  still needs the token.
- The Host header must be a loopback name, the local address the request arrived on, or listed
  in `mcp_http_allowed_hosts` (else 421). A browser Origin must be the request's own origin, a
  loopback origin on a loopback Host, or listed in `mcp_http_allowed_origins` (else 403). Both
  checks apply to SSE and streamable HTTP.
- `mcp_http_client_tokens` gives each app its own token, for example
  `{"cursor": "...", "claude-code": "..."}`. Names are slugged the same way as clientInfo names
  (see the slug list under Provenance). A write made with an app's token is recorded as that app
  in provenance, whatever its clientInfo says. The shared `mcp_http_token` names no app, so
  provenance falls back to clientInfo. Every configured token must be different.
- Tokens are compared in constant time and never logged. `bm config list` and `bm config get`
  show `mcp_http_token` as `********`, and `basic_memory_diagnostics` (which every connected app
  can call) leaves all of them out. Basic Memory writes `config.json` with mode 0600 inside a
  0700 directory. Put tokens there or in the environment. `bm config set mcp_http_token <token>`
  works but leaves the token in your shell history, and `bm config set` does not take the host,
  origin, and per-app settings because they are lists and maps.
- Plain HTTP carries the token in clear text. Keep the server on loopback, or put TLS in front
  of it. For Docker, see [Docker.md](Docker.md).

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

## Brief

`get_brief(project, token_budget)` and `memory://_brief/{project}` return a bounded
orientation. `bm brief` and the setup hooks print the same text. There is one
implementation; the setup command does not keep a second brief.

Settings (env vars use the `BASIC_MEMORY_` prefix):

- `brief_state_note` (default `project/state`) — included when the note exists
- `brief_profile_note` (default `me/profile`) — optional excerpt when the note exists;
  missing notes are omitted with no error text
- `brief_include_profile` (default `false`) — when false, `get_brief` omits that excerpt
  even if the note exists. Turn it on to include the profile
- `brief_inject_enabled` (default `false`; `bm setup --brief`) — when false, Cursor
  `sessionStart` and Claude Code `UserPromptSubmit` inject nothing. Titles are not
  injected either: a title can be as sensitive as the body. Calling `get_brief`
  still returns the briefing
- `brief_inbox_folder` (default `inbox`) — top-level markdown files counted in the brief
- `brief_decision_days` (default `14`) — decision note titles listed by search
- `brief_token_budget` (default `1500`) — rough character budget (`len / 4`); later
  sections drop first
- `brief_refresh_hours` (default `6`) — minimum time between deliveries for the same
  conversation (`bm brief --conversation <id>`, or `--conversation-id`; `--force` overrides).
  `get_brief(conversation_id=...)` uses the same clock and records the id when you pass one

Delivery timestamps are stored in `<project>/.basic-memory/brief-delivery.json`.

`bm setup --brief` wires delivery. Without that flag the hook commands are not
installed, and a later setup without `--brief` removes them. When the flag is off
at runtime, Cursor prints `{}` and Claude Code prints nothing.

- Claude Code `UserPromptSubmit` prints JSON `hookSpecificOutput.additionalContext`
  (event name `UserPromptSubmit`). That runs on every prompt, including a resumed
  session, and injects the brief when the refresh window has elapsed. Official docs
  also add plain stdout to context on exit 0; the hook prints only the JSON object so
  the brief is not parsed as a broken decision.
- Cursor `sessionStart` prints `additional_context`. Cursor's docs say this hook runs
  when a **new** composer conversation is created, and the text is initial system
  context. It does not run when you reopen an old chat. `beforeSubmitPrompt` can only
  return `continue` and `user_message` (a message shown when the prompt is blocked),
  so setup does not register it.
- In a resumed Cursor chat the brief is not injected by a hook. Setup writes a
  machine-local rule file at `~/.cursor/rules/basic-memory-get-brief.mdc` and prints
  the same text. With injection off, the rule says not to read project notes unless
  you ask. With `--brief`, the rule asks the model to call `get_brief`. The rules
  reference ([cursor.com/docs/rules](https://cursor.com/docs/rules)) defines global
  user rules only in Customize → Rules (account-synced, no file API). The help page
  ([cursor.com/help/customization/rules](https://cursor.com/help/customization/rules))
  also documents user rule files in `~/.cursor/rules` that stay on the machine.
  Following the rule is not guaranteed. `--uninstall` removes or restores the file.
  A rule pasted into Customize → Rules stays until you delete it there.

See [FORK_SETUP_CURSOR_HOOKS.md](FORK_SETUP_CURSOR_HOOKS.md).

## Local usage log and `bm stats`

Settings (local only; default on):

| Setting | Default | Env |
| --- | --- | --- |
| `usage_log_enabled` | `true` | `BASIC_MEMORY_USAGE_LOG_ENABLED` |
| `usage_log_retention_days` | `90` | `BASIC_MEMORY_USAGE_LOG_RETENTION_DAYS` |

`brief_refresh_hours` (default `6`, see Brief) is the same clock the prompt-submit hooks use
when deciding whether a resumed conversation should get another brief.

Each project writes JSON lines to `<project>/.bm-logs/events-YYYY-MM-DD.jsonl` (UTC). The folder
is mode `0700`, files `0600`, contains a `.gitignore` with `*`, and is excluded from indexing.
Logs may contain permalinks and harness conversation ids. They never contain note bodies, full
queries or prompts, or bearer tokens. Search queries log only length plus a short salted hash
(salt file `usage_log_query_salt` in the config dir, mode `0600`).

The long-running MCP server records tool calls through middleware (non-blocking queue, about 1 s
or 100 events per flush). Files named `events-YYYY-MM-DD.jsonl` older than
`usage_log_retention_days` are deleted when the MCP server starts and on the first append
of a hook process. Per-turn harness hooks use a stdlib-only append path:

- `bm hook prompt-submit --harness claude|cursor`
- `bm hook turn-end --harness claude|cursor`
- `bm hook post-mcp-tool --harness claude|cursor`

`bm stats [--days N] [--json] [--project P]` reads only these local files. Terminal output may
show conversation ids and permalinks; `--json` is aggregate-only for automation.

**Harness capabilities verified in fixtures:** Claude Code sends `session_id` on
UserPromptSubmit, Stop, and PostToolUse; tool names arrive as `mcp__basic-memory__<tool>`.
Cursor desktop fixtures include `conversation_id` on beforeSubmitPrompt, stop, and
afterMCPExecution plus `tool_name` on afterMCPExecution.

**Cursor coverage:** `sessionStart` fires for a new composer chat, not when a month-old
chat is reopened. `beforeSubmitPrompt` cannot inject context. Cursor cloud agents do
not load these hooks. A resumed Cursor chat gets no automatic brief. The user rule
file from `bm setup` is a model-followed reminder to call `get_brief`, not a hook.
HTTP clients without hooks (ChatGPT, Grok) get INFERRED session stats from MCP logs
using a 30-minute idle gap.

## Session capture (v2)

Off by default (`session_capture_enabled`). `bm setup --session-capture` turns it on
and only then registers the Cursor `stop` and Claude Code `Stop` hooks. A later
`bm setup` without that flag removes those hooks.

When a stop payload contains conversation text (`prompt`, `text`, `transcript`,
`messages`, or a response field), the hook appends that text, clipped, to one local
note `inbox/session-<id>.md`. Credential-like fields are replaced with `[redacted]`.
The note is ordinary markdown, so search can find it. A stop that is only a status,
which is what Cursor's documented stop input is, writes nothing. The same payload
twice does not append twice. Nothing in this feature is uploaded.

## Local history

Before `write_note`, `edit_note`, `move_note`, and a single-file `delete_note` change
an existing file, the fork copies that file into `<project>/.bm-history/` and records
the checksum of those bytes. If the file changes after the copy, the write or delete
raises and the newer bytes stay. A directory `delete_note` or `move_note` copies every
regular child first. A local directory delete then removes only those copied paths; a
path that was not copied, or whose checksum changed, is left in place. Symlinks are
not followed, `.bm-history` is not copied into itself, and a symlinked `.bm-history`
is refused. `.bm-history` is in the default ignore patterns and the `.bmignore`
template, next to `.bm-logs`. If any copy fails, the delete raises and the files stay.
There is no restore command; the copies are ordinary files.

A permalink insert or update edits only that frontmatter line (or prepends a fence
when the note has none). Other bytes, including `yes`, flow lists, timestamps, and
trailing blank lines, stay as they were. The first time a project is indexed
(`last_scan_timestamp` is empty), the log says so and names the display name and
config key. Pause Obsidian Sync before that first launch.

## Setup

`bm setup` is safe to run again. It reuses `~/.basic-memory/fork-mcp-tokens.json` and
does not mint new tokens. `--uninstall` copies back the files it changed and deletes
files it created, including a `config.json` that did not exist before, the launchd
plist template, and the Cursor rule file when setup created it.

Every MCP entry (`~/.cursor/mcp.json`, Claude Desktop, and `~/.claude.json`) gets
`env.BASIC_MEMORY_NO_PROMOS=1` and `env.BASIC_MEMORY_FORCE_LOCAL=1`. The launchd
plist sets both. Setup also writes `logfire_enabled=false`,
`logfire_send_to_logfire=false`, and `cloud_promo_opt_out=true`. If a cloud API key,
OAuth tokens, a default workspace, or a cloud-mode project is already configured,
setup stops with an error and does not write MCP entries. Uninstall restores the
previous `config.json`, so a Logfire setting you had before setup comes back.

Claude Code user-scope MCP servers are written to `~/.claude.json` (`mcpServers`),
which is where `claude mcp add --scope user` writes them. `~/.claude/settings.json`
receives hooks only. Cursor MCP goes to `~/.cursor/mcp.json`. The hook command is the
absolute path of the fork binary.
