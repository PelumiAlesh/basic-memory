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
get_brief(project=None, project_id=None, token_budget=None,
          conversation_id=None)
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
`brief_profile_note` exists (default `me/profile`) and `brief_include_profile`
is true (the default). Missing profile or state notes are omitted with no error
text. Setting `brief_include_profile` false omits the profile excerpt even when
the note exists.

`token_budget` overrides `brief_token_budget` (default 1500). The renderer uses
roughly four characters per token; later sections are dropped first.

`bm brief --conversation-id` records delivery time in
`<project>/.basic-memory/brief-delivery.json` and skips output until
`brief_refresh_hours` (default 6) elapse unless `--force` is set.
`get_brief(conversation_id=...)` records the same store and, inside that window,
returns a one-line already-delivered notice instead of another brief.

## PARAMETERS

- **project** (string | null, optional, default: None)
- **project_id** (string | null, optional, default: None)
- **token_budget** (integer | null, optional, default: None)
- **conversation_id** (string | null, optional, default: None)

## SEE ALSO

`read-note(3)`, `search-notes(3)`, `list-directory(3)`, `docs/SHARED_MEMORY.md`
