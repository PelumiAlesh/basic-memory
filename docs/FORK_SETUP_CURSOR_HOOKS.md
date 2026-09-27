# Cursor brief delivery (fork setup)

`bm setup` registers one Cursor hook that can carry context: `sessionStart`.

Cursor's hook docs say `sessionStart` runs when a **new composer conversation is
created**. The output field `additional_context` is "additional context to add to the
conversation's initial system context." Reopening a chat you already have does not
create that conversation, so the hook does not run. Someone who resumes month-old
chats does not get the brief injected on those chats.

`beforeSubmitPrompt` runs on send, including in an old chat, but its output is only
`continue` and `user_message`. `user_message` is shown to the person when the prompt
is blocked. It is not added to the model's context. Setup does not register that
hook, because it cannot deliver the brief and it would start the CLI on every send.

No other Cursor hook is documented as injecting context at the start of a resumed
chat. `stop` can auto-submit a `followup_message` after the agent finishes, which is
a new user turn, not a brief at the start of an old chat. Setup does not use it for
the brief.

What Cursor does get:

- A new chat: `sessionStart` prints `{"additional_context": "<brief>"}` when this
  conversation id has not had a brief within `brief_refresh_hours` (default 6).
  Cursor staff have also reported a race where that field is dropped even though the
  Hooks log says it merged. This repo cannot fix that race.
- An old chat: no injected brief. `bm setup` writes
  `~/.cursor/rules/basic-memory-get-brief.mdc` (`alwaysApply: true`) and prints the
  same text. [The rules reference](https://cursor.com/docs/rules) defines global user
  rules only in Customize → Rules. Those sync with the account, and there is no file
  API for them. [The help page](https://cursor.com/help/customization/rules) also says
  user rule files in `~/.cursor/rules` stay on the machine and do not sync. The file
  asks the model to call `get_brief` at the start of a turn when it has not called
  `get_brief` in that conversation within the last 6 hours, and to pass
  `conversation_id` when it has one so the tool can record the delivery. Following
  the rule is not guaranteed. `--uninstall` removes or restores the file only. A
  rule pasted into Customize → Rules stays until you delete it there. Setup does not
  write a project `.cursor/rules` file, because that would apply in only one repo.
- Cursor cloud agents: the docs say `sessionStart` is deferred because hooks do not
  load while the agent starts read-only.

Claude Code is different. `UserPromptSubmit` runs on every prompt, including a
resumed session, and `hookSpecificOutput.additionalContext` is added to Claude's
context. See `docs/SHARED_MEMORY.md`.

Sources: [Cursor hooks](https://cursor.com/docs/hooks),
[Cursor rules](https://cursor.com/docs/rules),
[Cursor rules help](https://cursor.com/help/customization/rules),
[Claude Code hooks](https://code.claude.com/docs/en/hooks-guide).
