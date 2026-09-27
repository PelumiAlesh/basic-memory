# Cursor brief delivery (fork setup)

Fork setup wires `sessionStart` to re-deliver the Basic Memory brief via
`additional_context` when the harness conversation id has no recent delivery
(within `brief_refresh_hours`, default 6).

`beforeSubmitPrompt` is registered for symmetry with Claude Code per-turn hooks,
but **Cursor's hook schema does not support context injection on that event**
(only `continue` and `user_message`). Brief injection on Cursor therefore
happens on `sessionStart` (resume/new session), not on every prompt submit.

See [Cursor hooks](https://cursor.com/docs/hooks) and community reports that
`beforeSubmitPrompt` cannot carry `additional_context`.
