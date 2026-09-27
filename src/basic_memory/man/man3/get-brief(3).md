---
title: get-brief(3)
type: manpage
section: 3
name: get-brief
summary: bounded project briefing for clients without session hooks
generated: registry
tool: get_brief
verified: fork
---

# get-brief(3)

## NAME

**get-brief** — bounded project briefing for clients without session hooks

## SYNOPSIS

MCP:

```
get_brief(project=None, project_id=None, token_budget=None)
```

CLI:

```
bm brief [--project NAME] [--conversation-id ID] [--refresh-hours HOURS]
         [--force] [--harness] [--local | --cloud]
```

Resource:

```
memory://_brief/{project}
```

## DESCRIPTION

Returns a short markdown briefing: current-state excerpt when `brief_state_note`
exists (default `project/state`), decision note titles from the last
`brief_decision_days` (default 14), a count of markdown files in
`brief_inbox_folder` (default `inbox/`), and an optional profile excerpt when
`brief_profile_note` exists (default `me/profile`). Missing profile or state
notes are omitted with no error text.

`token_budget` overrides `brief_token_budget` (default 1500). The renderer uses
roughly four characters per token; later sections are dropped first.

`bm brief --conversation-id` records delivery time in
`<project>/.basic-memory/brief-delivery.json` and skips output until
`brief_refresh_hours` (default 24) elapse unless `--force` is set.

## PARAMETERS

- **project** (string | null, optional, default: None)
- **project_id** (string | null, optional, default: None)
- **token_budget** (integer | null, optional, default: None)

## SEE ALSO

`read-note(3)`, `search-notes(3)`, `list-directory(3)`, `docs/SHARED_MEMORY.md`
