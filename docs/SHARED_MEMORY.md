# Shared memory across clients

This fork keeps one Markdown vault as the memory for ChatGPT, Cursor, Claude
Code, and other MCP clients. The features below are config-gated. Defaults
match upstream except where a feature is the safer default: HTTP binds to
loopback, and discovery search hides `superseded` and `archived` notes.

`created_by` on an entity is still the cloud account id. Client identity is
separate and lives in frontmatter.

## 1. Provenance

`record_provenance` (default `true`). Env: `BASIC_MEMORY_RECORD_PROVENANCE`.

When an MCP client sends `clientInfo`, `write_note` and `edit_note` set:

- `source_client` — who wrote this revision (`cursor`, `claude-code`, `chatgpt`, `grok`, …)
- `updated` — UTC timestamp
- `created_by_client` — set on the first write and kept after that

Writes with no client identity are unchanged. Search text results list the
fields when the index has them. Read results include them in frontmatter.

### Write verification

`verify_writes` (default `true`). Env: `BASIC_MEMORY_VERIFY_WRITES`.

After `write_note`, `edit_note`, `move_note`, and `delete_note`, the tool
reads the note back from the index and, for a local project, from disk
(after waiting up to five seconds for pending materialization). The response
ends with:

```
## Verification
status: verified
index: ok
disk: ok
```

`status` is `verified`, `pending` (the file write had not finished), or
`failed`. A failed verdict names the reason: `missing`, `truncated`,
`duplicated`, or `mismatch` for the index; `missing` or `mismatch` for the
file. JSON output carries the same under `verification`, sets
`error: WRITE_VERIFICATION_FAILED`, and turns `moved` / `deleted` false.
Cloud projects report `disk: remote`. This is the answer to the false
"saved" reports in upstream #1341, #1531, #1479, and #1585.

## 2. Secure HTTP

`basic-memory mcp --transport streamable-http` binds to `127.0.0.1` unless
you pass `--host` or set `mcp_http_host`. A non-loopback bind without a token
logs a warning.

Host and Origin are always checked (FastMCP's guard in strict mode). The
Host header must be loopback, the bound address, or a name in
`mcp_http_allowed_hosts`; anything else is answered 421. A browser Origin
must be same-origin, loopback, or in `mcp_http_allowed_origins`; anything
else is 403. Both are comma-separated. A tunnel hostname goes in
`mcp_http_allowed_hosts`.

Bearer token, never logged:

- `BASIC_MEMORY_MCP_HTTP_TOKEN` (client slug `mcp_http_token_client`, default `http`)
- `BASIC_MEMORY_MCP_HTTP_CLIENTS` as `chatgpt:secret,cursor:other`

`bm config list` redacts both fields.

This process does not mint OAuth tokens or validate JWTs. Set
`mcp_oauth_issuer` to an external authorization server and clients can read
`/.well-known/oauth-protected-resource` (RFC 9728). That document is public.
Everything else requires the bearer token when one is configured.

### ChatGPT developer mode

ChatGPT's connector expects streamable HTTP and the `search` and `fetch`
tools this server already exposes.

```bash
export BASIC_MEMORY_MCP_HTTP_TOKEN="$(openssl rand -hex 32)"
export BASIC_MEMORY_MCP_HTTP_TOKEN_CLIENT=chatgpt
export BASIC_MEMORY_MCP_HTTP_ALLOWED_HOSTS=memory.example.com
basic-memory mcp --transport streamable-http --port 8000
```

The server is only on localhost. Put a tunnel in front of it (Cloudflare
Tunnel or Tailscale Funnel) and give ChatGPT the public `https://…/mcp` URL
plus the bearer token. Do not bind `0.0.0.0` without the token.

For OAuth 2.1, run an authorization server that issues that same bearer
secret (or front the process with one) and set `mcp_oauth_issuer` to its
issuer URL. A full authorization server, dynamic client registration, and
PKCE are intentionally not inside the note store.

## 3. Brief

`get_brief(project, token_budget)` and `memory://_brief/{project}`.

Includes `brief_profile_note` (default `me/profile`), `brief_state_note`
(default `project/state`), decisions from the last `brief_decision_days`
(14), question and unreviewed counts, and notes from the last seven days.
`brief_token_budget` defaults to 1500. Later sections are dropped first.

## 4. Review inbox

Off unless `review_inbox_enabled=true`.

- `review_inbox_mode=status` (default): a newly created MCP note with no
  `status` gets `status: unreviewed`. Updates do not re-queue a note.
- `review_inbox_mode=folder`: an empty directory becomes
  `review_inbox_folder` (default `inbox`).

`bm review`, `bm review promote <id>`, `bm review merge <id> <target>`,
`bm review discard <id>`. MCP: `review_queue`, `review_note`.

## 5. Conflicts and inactive notes

`conflict_check_on_write` (default `true`). A `decision` or `preference`
write adds similar active notes flagged `possible conflict`. Set it false to
keep only the existing similar-note hint on create.

`search_exclude_inactive` (default `true`) hides `status: superseded` and
`status: archived` from discovery search. Notes with no status stay. Pass
`include_inactive=true`, or set `status` yourself, to see them. An exact
permalink lookup always finds them.

`supersedes:` in frontmatter (a string or a list of permalinks or titles)
marks those notes `status: superseded` after the write.

## 6. Recency and care

`search_recency_weight` defaults to `0`, so ranking is unchanged. Set it
between 0 and 1 to blend scores with an exponential decay
(`search_recency_half_life_days`, default 30). The blend runs inside a
bounded candidate window, not the whole project.

`bm care` lists notes past `review_by`, notes missing `source_client`,
orphans (the same query as `bm orphans`), and files larger than
`care_oversized_bytes` (default 100000). `bm doctor` is still the
file-to-database check and is not run from `care`.

## 7. Privacy

Frontmatter `visibility` is `private`, `work`, or `shareable`.

`client_visibility` is empty by default, and then nothing is filtered. It is
a map from client slug (provenance name or bearer-token client) to:

```json
{
  "chatgpt": {
    "deny_visibility": ["private"],
    "deny_path_prefixes": ["personal"]
  }
}
```

Env: `BASIC_MEMORY_CLIENT_VISIBILITY` as that JSON.

When any policy exists:

- A known client is held to its own lists. An empty policy means that client
  may read everything.
- An unknown client may read only `shareable` notes, and every configured
  path prefix is denied.
- Missing or unrecognized visibility counts as `private`.

The check runs in `read_note`, `search_notes`, `get_brief`, `read_content`,
the `memory://` note resource, and `build_context`. A denial returns no body.
`build_context` can only see visibility when the context payload still
contains frontmatter; otherwise a restricted client is denied that item.

The CLI is not an MCP client and is not filtered.

## 8. Git

`git_autocommit` defaults to false. When true, an MCP write or edit commits
that note file in the project repository after
`git_autocommit_debounce_seconds` (default 2). The message is
`memory(<client>): update <note>`.

`bm history <note>` is `git log` for that path. `bm undo` reverts the last
commit whose subject matches `memory(...):` and refuses any other HEAD or a
dirty tree. The root commit of a repository cannot be reverted; seed the
repo with one commit first.

`git_auto_push` defaults to false. A push runs only when it is true and
`git remote` prints a name. Credentials in git errors are stripped before
logging.

## 9. Cursor hooks

```bash
bm install cursor
# or: bm hook install --harness cursor
```

This writes `~/.cursor/hooks.json`:

- `sessionStart` → `bm hook session-start --harness cursor`
  (stdout is `{"additional_context": "<brief>"}`)
- `preCompact` → `bm hook pre-compact --harness cursor`

Set the project in `.cursor/basic-memory.json` or
`~/.cursor/basic-memory.json`:

```json
{"primaryProject": "main"}
```

Cursor cloud agents do not run user hooks, and they do not fire
`sessionStart`. Copy the same entries into the repo's `.cursor/hooks.json`
if a cloud agent should run them. `beforeSubmitPrompt` is not installed;
capture is the session-start envelope.

## 10. Notion import

```bash
bm import notion ~/Downloads/Export.zip
bm import notion ~/Downloads/Export --destination imports/notion
```

Accepts the Markdown & CSV zip or the unpacked folder. File and folder names
lose the trailing 32-character id. Relative links become `[[wiki links]]`.
Each CSV row becomes a note; column names are frontmatter keys. Hierarchy is
kept under the destination. A `*_all.csv` next to the plain CSV is skipped.
Zip entries that leave the extract directory are rejected.
