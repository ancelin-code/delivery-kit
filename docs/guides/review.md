# Review the Pull Requests

A lane's change is reviewed twice. Only the second review is yours to set up,
and setting it up is optional.

## The first review is automatic

Every lane ends with `etabli-refine`, a second session that did not write the
change. It reviews the change against the task's acceptance criteria on a
stronger model, fixes what it finds, simplifies it, and re-runs validation.
There is nothing to configure: it runs in every lane, and the Refinement
section of the pull request body says what it fixed, deferred and simplified.
See [The Six Skills](../concepts/skills.md#refinement-the-second-session).

## The second review is the merge gate

Review is the final gate. Everything before it ran unattended, so this is where
a person decides whether the work lands, and a refined change is not a reviewed
one. The kit ships no reviewer for this gate: use the harness's own review
capability, or install a review skill alongside the kit and compare it with the
unassisted harness before adopting it.

When you ask the orchestrator what is next, `where.sh` names, for each pull
request in review, the review skills worth running on it. Those names come from
`delivery/review-lenses.conf`, which is a suggestion for you, not something that
runs by itself.

## Lenses

A **lens** is a concern that deserves its own review pass, such as security or
data. The project names its lenses in `delivery/review-lenses.conf`, one per
line: the lens, the review skill that covers it (`-` for the harness's own review), and optionally
the path patterns that bring it in.

```text
# lens     skill             paths that bring the lens in
general    code-review
security   security-review   */auth/* *secret* *.tf
```

`install-routing.sh` writes a starter file that suggests only the harness's own
review, and it never overwrites an existing one. Edit it to map a concern to a
review skill installed in the project.

A pattern matches the whole path of a file the pull request changes, and `*`
crosses directories. `general` applies to every pull request. A pull request
needs a lens when any of these holds:

- its task lists the lens in `review`, set at decomposition
- a person labelled the pull request `review:<lens>`
- it changes a file matching one of the lens's patterns

A lens earns its place when its skill carries knowledge the general review
lacks. A lens that only asks the same reviewer to adopt another role does not;
drop it from the file. The full format is in the
[review lenses](https://github.com/ancelin-code/etabli/blob/main/.agents/skills/etabli-orchestrator/references/conventions.md#review-lenses)
convention.

## One pass is the default

Review once. Re-review only when the first pass found either a high-severity
issue, or at least three medium findings together with two or more low ones.
Without a rule like this, review loops until someone gets bored, and the later
passes reliably find less than they cost. A finding below that bar is recorded
on the pull request and fixed, not re-reviewed.

A finding names a concrete failure: the input or state that triggers it, and
what goes wrong. "This could be clearer" is a comment, not a finding.

## Reviewing an unattended lane

A lane ran without a human watching, so check the things a watching human would
have caught:

- does the diff stay inside the task's frozen scope, or did it grow
- is every acceptance criterion demonstrated by something that was actually run
- were validation steps skipped, and is that stated
- did any test get weakened or deleted to make validation pass

The last one is worth checking explicitly. It is the cheapest way to make a
failing run look successful, and it is easy to miss in a large diff.
