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

## Write verification: read the note back

Setting: `verify_writes` (default `true`; env `BASIC_MEMORY_VERIFY_WRITES`).

After the API accepts `write_note`, `edit_note`, `move_note`, or `delete_note`, the tool reads
the note back before it answers, so an app that is told a note was saved can rely on it.

What is compared:

- The note's body. Frontmatter is dropped, because Basic Memory rewrites it on every write
  (permalink, provenance), and runs of whitespace are collapsed. Everything else must match
  exactly: a body with extra text fails just like one with missing text.
- `write_note` expects the body of the `content` it sent.
- `edit_note` reads the note just before the edit, applies the same edit to that copy, and
  expects the result. If another app changed the note between that read and the edit, the
  check reports `mismatch` instead of guessing.
- `move_note` expects the note at the new path in the index with the same body. For a local
  project the new file must match and the old file must be gone. A case-only rename on a
  case-insensitive disk (the macOS default) is one file, not a leftover. Images, PDFs, and
  other non-markdown files are checked for presence only.
- `delete_note` expects the note gone from the index and, for a local project, its file gone
  from disk.

The index is always read. The file on disk is read only when this process writes the
project's files: a local project whose configured folder is the folder the API answered with.
A cloud project, a `--cloud` route, or a hosted app is checked in the index only, and the
result says so.

| Result | Text output | JSON output |
| --- | --- | --- |
| verified | `verification: verified (index and file)`, or `(index only; ...)` | `"verification": {"status": "verified", "disk_checked": true}` |
| pending | `verification: pending (<why>)` | `{"status": "pending", "detail": "<why>"}` |
| failed | an error in place of the success message | `{"status": "failed", "reason": "<reason>", "detail": "<what>"}`, plus `"error": "WRITE_VERIFICATION_FAILED"`; `moved` or `deleted` is `false` |

`delete_note` text output stays a bare `True` when the delete is confirmed.

Failure reasons:

- `missing`: the note is not in the index after a write or move.
- `truncated`: the stored body is a cut-short copy of the expected one.
- `duplicated`: the text this call wrote appears more times than it should, at any length.
- `mismatch`: any other difference, including an edit that raced another app, or a move
  indexed at a different path.
- `empty`: the body would be empty (see Limits).
- `file_missing`, `file_differs`: the file on disk is gone or does not match the index. The
  detail names the file write status and its last error.
- `still_indexed`, `file_remains`: a delete that did not take. A file left on disk would put
  the note back in the index on the next sync.
- `source_remains`: a move that left the old file, so the note now exists twice on disk.

Pending means the write was accepted but not confirmed: the file writer had not finished
within 5 seconds, or reading the note back failed with anything other than "not found". A
read error is never reported as a failed write, because a retry could apply the write twice.

Limits:

- A body that is empty after the call is never reported as verified: an empty body is also
  what a write that lost everything looks like. That includes a metadata-only `edit_note` on a
  note with no body.
- Frontmatter is not checked. A metadata-only edit is verified only for leaving the body alone.
- Directory moves and deletes (`is_directory=True`) are not read back. Their results already
  list every file that failed.
- The check costs one read after each write, and for `edit_note` one more before it. With
  `verify_writes` off the tools answer as upstream does, and JSON output has
  `"verification": null`.
- The 5-second wait covers this process's own file writer. If another app changes the note
  between the write and the read-back, the check fails even though this call's write landed.
