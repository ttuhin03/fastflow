# Working in this repo

This file applies to any agent (Claude Code or otherwise) committing to fastflow.

## Commit messages

Write commit messages the way the existing history does — like a person describing
the change, not a bot logging a task:

- Imperative mood, capitalized first word: `Add`, `Update`, `Fix`, `Refactor`, `Enhance`, `Implement`.
- One line, no trailing period, no ticket/issue IDs, no agent or tool name in the message.
- Describe the change and its purpose, not the process used to make it.

Examples from this repo's actual log:
- `Refactor path validation in main.py for improved security`
- `Add security scan workflow for IaC, image vulnerabilities, and secret scanning`
- `Update README.md to clarify Fast-Flow's positioning and feature comparisons`
- `Implement OAuth CSRF protection with state management`

Avoid: `TE-7: verify persistent push access (visible test branch)`, `WIP`, `test commit`,
`[agent] did X`, or anything referencing an internal issue tracker, run ID, or agent name.

## Branch names

Follow the two patterns already used in this repo:

- Topic branches for a body of related work: `<area>/<short-kebab-description>`
  (e.g. `security/dast-auth-and-scanning`).
- Short-lived agent working branches: `claude/<adjective>-<noun>-<shorthash>`
  (e.g. `claude/friendly-goodall-39c00d`).

Avoid embedding issue IDs, the word "paperclip", agent names, or literal status words
like `verified`/`test`/`done` in the branch name — describe the work itself.

## Why this matters

Commit history and branch names are read by humans (and by other agents doing
`git log`/`git blame` for context). Keeping them consistent with the project's existing
style keeps that history useful instead of turning it into a log of internal tooling.
