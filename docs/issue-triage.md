# Issue triage

The triage workflow runs on odd-numbered UTC calendar dates at 09:17. It is best effort, not an
exact 48-hour service level. A maintainer can use **Run workflow** in dry-run mode to see every
unlabeled candidate, then use backfill only after reviewing that result. Scheduled runs consider
only issues created after `TRIAGE_ROLLOUT_AFTER` in `.github/workflows/issue-triage.yml`.

## Labels

| Axis | Labels | Owner |
| --- | --- | --- |
| Queue | `triage: needs-review`, `triage: discussed` | Bot adds only `needs-review`; maintainers transition it after discussion. |
| Priority | `priority: high`, `priority: medium`, `priority: low` | Maintainer, after a decision comment. |
| Contribution | `contribution: proposed`, `contribution: available`, `contribution: claimed` | The form adds `proposed`; maintainers control target-issue availability and claims. |

Existing labels such as `bug`, `enhancement`, and `documentation` remain independent. The bot never
removes labels, closes issues, locks them, assigns people, or applies terminal labels.

## Maintainer decision record

Before changing priority, contributor state, or closure, comment with the decision, rationale, next
action, and a revisit trigger if the issue becomes low priority. Low-priority issues remain open.

Implementation PRs use `Refs #<number>`. After merge, a maintainer records the merged PR,
verification, and closure rationale in the issue, then closes manually when appropriate.
