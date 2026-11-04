# The Route

The route takes a project from an intent to merged pull requests. Each phase
writes a file, the next phase reads it, and a person approves the file before
the route goes on, so no session has to stay alive across a gate.

<div class="route-fig" role="group" aria-label="The route: requirements and design once, then cut, build, review and milestone review for each milestone">
  <p class="route-fig__label route-fig__label--once">Once, for the whole project</p>
  <ol class="route route--once">
    <li class="route__step">
      <span class="route__n">1</span>
      <a class="route__name" href="../prd/">Requirements</a>
      <span class="route__skill"><code>/etabli-spec</code> stage A</span>
      <span class="route__file">delivery/prd.md</span>
      <span class="route__badge">You approve</span>
    </li>
    <li class="route__step">
      <span class="route__n">2</span>
      <a class="route__name" href="../skills/#why-the-spec-is-one-skill">Design spine</a>
      <span class="route__skill"><code>/etabli-spec</code> stage B</span>
      <span class="route__file">decision records, contracts</span>
      <span class="route__badge">You approve</span>
    </li>
  </ol>
  <p class="route-fig__label route-fig__label--loop">Once per milestone</p>
  <ol class="route route--loop">
    <li class="route__step">
      <span class="route__n">3</span>
      <a class="route__name" href="#how-the-work-is-cut">Cut</a>
      <span class="route__skill"><code>/etabli-decompose</code></span>
      <span class="route__file">decomposition summary, task files</span>
      <span class="route__badge">You approve</span>
    </li>
    <li class="route__step">
      <span class="route__n">4</span>
      <a class="route__name" href="../lanes/">Build</a>
      <span class="route__skill"><code>/etabli-implement</code><code>/etabli-refine</code></span>
      <span class="route__file">one lane per task, ending in a draft pull request</span>
      <span class="route__badge route__badge--auto">Unattended</span>
    </li>
    <li class="route__step">
      <span class="route__n">5</span>
      <a class="route__name" href="../../guides/review/">Review and merge</a>
      <span class="route__skill">a review skill, or the harness's</span>
      <span class="route__file">the pull requests</span>
      <span class="route__badge">You merge</span>
    </li>
    <li class="route__step">
      <span class="route__n">6</span>
      <a class="route__name" href="#milestones-are-the-default">Milestone review</a>
      <span class="route__skill"><code>/etabli-decompose</code></span>
      <span class="route__file">the milestone review note</span>
      <span class="route__badge">You approve</span>
    </li>
  </ol>
  <p class="route__loop">Another milestone to go? Back to 3, and cut it with what the review taught you.</p>
</div>

## Milestones are the default

A **milestone** is a slice of the project that works end to end and that you
can run and test. Think of it as an MVP in the agile sense: some of its
features may be very simple, stubbed or missing, but what exists runs. The first
milestone is usually a walking skeleton that runs the riskiest parts, such as
sign-in, a remote connector or the deployment, from one end to the other. Each
next milestone adds to a product that already works.

The orchestrator plans milestones for every full route, and cuts the first one
only. If it thinks they make no sense for your project, it tells you why and
asks. The decision is yours alone, and it is written in the decomposition
summary.

!!! tip "Keep the milestones"

    **Without milestones, the route is one pass and is not incremental.** The
    whole scope is cut into tasks and built before anyone has a working product
    in hand, so what you learn from a first running version cannot reshape the
    rest. You can still revise the requirements and cut again, but nothing in
    the route makes you stop, look at the result and adjust.

    Decline them only for a project you can hold in your head, and say so when
    the orchestrator asks. To steer them, say it in your request, for example
    `/etabli-orchestrator <what to build>, riskiest part first`, and check the
    milestone plan when you approve the decomposition.

How a milestone runs:

1. **Planned up front.** The milestone plan, in `delivery/decomposition.md`,
   lists every milestone with an **exit criterion**, which says what must work,
   and the requirement ids it targets. The requirements and the design stay
   whole, written for the project in full. Only decomposition and building are
   incremental.
2. **Cut one at a time.** Only the current milestone is cut into epics and
   tasks, and the validator rejects tasks of a later one. Cutting is deferred on
   purpose, so what the first slice teaches can shape the second.
3. **Built and merged.** Lanes build the tasks, and you review and merge their
   pull requests.
4. **Reviewed.** A short note, `delivery/milestones/<slug>.md`, records whether
   the exit criterion held, what was learned, what is left of each requirement,
   and whether to continue or to revise the requirements or a decision first.
   Only a person running the slice can say it works, so the criterion is not
   checked by a machine. Approving the note closes the milestone.
5. **Next.** The next milestone is cut with the note in hand.

## How the work is cut

<div class="route-fig" role="group" aria-label="A project holds milestones, a milestone holds epics, an epic holds tasks; only the current milestone is cut">
  <div class="nest">
    <div>
      <span class="nest__tag">Project: one repository, one requirements document</span>
      <div class="nest__milestones">
        <div class="nest__milestone">
          <strong>Milestone 1: the current one, cut</strong>
          <div class="nest__epic">
            <span class="nest__tag">Epic</span>
            <div class="nest__chips"><span class="nest__chip">a-001</span><span class="nest__chip">a-002</span><span class="nest__chip">a-003</span></div>
          </div>
          <div class="nest__epic">
            <span class="nest__tag">Epic</span>
            <div class="nest__chips"><span class="nest__chip">b-001</span><span class="nest__chip">b-002</span></div>
          </div>
        </div>
        <div class="nest__milestone nest__milestone--later">
          <strong>Milestone 2</strong>
          Planned, not cut: no tasks yet.
        </div>
        <div class="nest__milestone nest__milestone--later">
          <strong>Milestone 3</strong>
          Planned, not cut: no tasks yet.
        </div>
      </div>
    </div>
    <p class="nest__note">Each task is one branch, one lane and one pull request.</p>
  </div>
</div>

- A **project** is a repository: one team, one set of requirements.
- A **milestone** is an optional, ordered slice with an exit criterion.
- An **epic** is a coherent group of work that one person can hold in their
  head. A group that delivers two separate outcomes is two epics.
- A **task** is one unit of work: one branch, one lane, one pull request.

A project whose user decided against milestones has the same epics and tasks in one flat set. The
definitions the agents apply are in the
[delivery conventions](https://github.com/ancelin-code/etabli/blob/main/.agents/skills/etabli-orchestrator/references/conventions.md#projects-epics-and-tasks).

## The artifacts

Every artifact lives under `delivery/` at the repository root, except the
decision records, which go in the decision record directory the repository
already has (`docs/adr/` or `docs/decisions/`), else in `delivery/decisions/`.
No agent has to search for one: when a file is not at its path, it does not
exist yet.

| Artifact and path | Written by | What it is for |
|---|---|---|
| [Requirements, the PRD](prd.md)<br>`delivery/prd.md` | `etabli-spec`, stage A | What must be true when the project is done, what must not change, and what is out of scope. Everything else is built from it. |
| Decision records (ADRs)<br>`ADR-<nnn>-<slug>.md` | `etabli-spec`, stage B | The choices that keep separately built parts compatible, with the alternatives that lost and why. |
| Contracts<br>`delivery/contracts/<interface>.md` | `etabli-spec`, stage B | The written shape of an interface two lanes must agree on, so lanes depend on a document and never on each other's unfinished code. |
| Decomposition summary<br>`delivery/decomposition.md` | `etabli-decompose` | The milestone plan (or the user's recorded decision against milestones), what each epic delivers, where the work runs in parallel or in series, and why it was cut this way. |
| Task files<br>`delivery/tasks/<id>.md` | `etabli-decompose`, or the orchestrator on the direct path | One unit of work: acceptance criteria, scope, dependencies, files it touches and its tier. A lane builds from it. |
| Milestone reviews<br>`delivery/milestones/<slug>.md` | `etabli-decompose`, with you | Whether the exit criterion held, what was learned, and whether to continue or revise. Read by the next cut. |
| Handoff report<br>`.lane-report.md` | `etabli-implement`, extended by `etabli-refine` | What changed, which validation ran, what was deferred and what the review fixed. It becomes the pull request body, so it is what you read first. |
| Review lenses<br>`delivery/review-lenses.conf` | `install-routing.sh` seeds it, you edit it | Which review skills the orchestrator suggests for a pull request. See [Review the Pull Requests](../guides/review.md). |
| Tier mapping, optional<br>`delivery/tiers.conf` | You | What `plan`, `build` and `chore` mean for the team. See [Choose Models with Tiers](../guides/tiers.md). |

You approve the requirements, the design spine, the decomposition (summary and
tasks), each merge, and each milestone review. The lanes between the
decomposition and the pull requests run unattended.

## Two ways through

The orchestrator investigates the request and the code before choosing how
much of the route to use:

| Path | When | What runs |
|---|---|---|
| Direct implement | One well-understood change with obvious acceptance criteria | one task file, then `etabli-implement` and `etabli-refine` in the ordinary checkout; no claim, no worktree, only the merge gate |
| Full route | Several tasks, contracts to keep parallel work consistent, or a decision worth recording | every phase and every gate, up to three lanes at once |

How much of a full route runs in parallel is decomposition's finding, not a
choice made up front; see [Parallel or serial](lanes.md#parallel-or-serial).

## Requirement coverage

Requirements carry ids. Tasks name the requirement ids they cover, in full or
in part, so `etabli-status/scripts/coverage.sh` can say what is left of each
requirement. That is what makes a milestone review concrete: it starts from
what each requirement still lacks, not from a feeling.
