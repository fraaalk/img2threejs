# Agent instructions

Cross-agent companion to `CLAUDE.md`. Read by agents that do not consume `CLAUDE.md`
(Codex, opencode, and other tooling that follows the `AGENTS.md` convention).

## Commit rules

- Commit under the repository owner's identity only.
- Never add `Co-Authored-By`, `Co-authored-by`, or any other agent-attribution trailer to commit
  messages, even when the work was produced by an agent.
- Message-only rewrites of a reviewed branch are allowed with `--force-with-lease`; never
  force-push a shared branch without that lease.
