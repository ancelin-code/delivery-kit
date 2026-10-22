# Review

Review is the final gate. Everything before it ran unattended, so this is where
a human decides whether the work lands.

The kit ships no reviewer for this gate, so these rules apply to whichever one
runs: the harness's own review capability, or a review skill installed alongside
the kit. A lane's change has already been through `delivery-refine`, which
reviewed it against its task on a stronger model and fixed what it found; its
Refinement section in the pull request body says what it fixed, deferred and
simplified. The human review is still the gate.

## Choosing the reviewer

`where.sh` names the review skill for each lens a pull request needs, from the
project's [review lenses](conventions.md#review-lenses). Run one pass per row.
The budget below applies to each pass, not to the pull request as a whole.

A lens earns its place when its skill carries knowledge the general review
lacks. A lens that only asks the same reviewer to adopt another role does not;
drop it from the file.

## Budget

**One review pass is the default.** Re-review only when the first pass found
either a high-severity issue, or at least three medium findings together with
two or more low ones.

Without a rule like this, review loops until someone gets bored, and the later
passes reliably find less than they cost. A finding below that bar is recorded
on the pull request and fixed, not re-reviewed.

## What a finding must contain

A finding names a concrete failure: the input or state that triggers it, and
what goes wrong. "This could be clearer" is a comment, not a finding.

Requiring a concrete failure mode is what separates a review that improves the
change from one that generates discussion. A reviewer who cannot state the
failure has not found one.

## Two lenses worth the tokens

Run these against the diff, in addition to whatever general review is used:

- **Edge cases.** What input does this change handle incorrectly? Empty,
  missing, duplicated, out of order, concurrent, or at a boundary.
- **Verification gap.** *If this behavior broke, would any test fail?* A change
  whose behavior nothing exercises is untested however many tests exist in the
  file.

These are prompts about method, not personas. Asking for concrete findings and
for what is missing improves results; instructing a reviewer to adopt an
attitude does not.

## Reviewing an unattended lane

A lane ran without a human watching, so check the things a watching human would
have caught:

- does the diff stay inside the task's frozen scope, or did it grow
- is every acceptance criterion demonstrated by something that was actually run
- were validation steps skipped, and is that stated
- did any test get weakened or deleted to make validation pass

The last one is worth checking explicitly. It is the cheapest way to make a
failing run look successful, and it is easy to miss in a large diff.
