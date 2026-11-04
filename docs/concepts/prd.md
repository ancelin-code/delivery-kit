# The Requirements (PRD)

The PRD, the product requirements document, is `delivery/prd.md`. It is the
first file the route writes and the one everything else is built from: the
decisions and contracts answer it, the tasks cite its ids, and the coverage of
each requirement is derived from them. A repository has one, and you approve it
before anything is designed or cut.

It says **what** must be true and **why**, never **how**. Choosing a technology
or a structure comes later, in the [design spine](route.md#the-artifacts),
with better information.

## What it contains

| Section | What goes in it |
|---|---|
| Status and approval | `draft` or `approved`, and who approved it, and when. |
| Problem | Two or three sentences: what is wrong or missing today, and for whom. No solution here. |
| Outcomes | What must be true when the work is done, each one observable, each with a stable id. The tasks and the milestones point at these ids. |
| Invariants | What must not change. They protect the existing system and bound every lane. |
| Out of scope | The nearby things somebody would otherwise build, named so no lane invents them. |
| Assumptions | What was assumed rather than asked, and what changes if it is wrong, so you can correct it in one pass. |
| Open questions | What genuinely blocks work, and who can answer it. |
| Sources | The material it was built from. |

Three of these carry the weight: the outcomes, the invariants and what is out of
scope.

## What an outcome looks like

An outcome is something a reader can check, and its id never changes. This
excerpt is invented, to show the shape:

```markdown
## Outcomes

- **R1.** A member signs in with their work account and reaches their own
  store without an administrator creating anything for them.
- **R2.** Searching a store returns only the pages its member may read.
- **R3.** Restoring a backup brings back every store, with its history.
```

An intention such as "the server should be secure" is not an outcome, because
nobody can say whether it holds. And "store the index in PostgreSQL" is a design
decision, not a requirement: the requirement is what the storage must do.

When the requirements change, the ids that survive stay as they are, and an id
that was dropped is never reused. That is what lets a task, or a milestone,
keep pointing at the same requirement over time.

## How it is written

`etabli-spec` writes it with you, in four moves:

1. **Explore.** It reads your sources and the existing code, and forms a view
   of what is being asked. Nothing is written as a requirement yet. The aim is
   to find disagreements and unknowns while they are still cheap.
2. **Ask.** At most five questions, asked together, and only ones whose answer
   would change what gets built. An answer it could reasonably assume is stated
   as an assumption instead, for you to correct.
3. **Write.** It writes `delivery/prd.md` from the template, for somebody who
   was not in the conversation.
4. **Check.** It tests the document before handing it over: could a developer
   who missed every conversation start from this, and is each requirement
   observable?

Then it stops, and you approve. The document is as long as it needs to be and no
longer: the real test is that `etabli-decompose` can cut it into tasks without
asking anything and without re-reading your sources.

## Reading it before you approve

Read it as the person who will live with the result. The outcomes should be the
product you want, the invariants should list what you would hate to see break,
and out of scope should name what you do not want built yet. Anything you
disagree with now is cheap to change; found during integration, it is not.

Approving it does not freeze it. Ask the orchestrator for a change and the same
file is revised, and the decomposition turns the new work into new epics.

## The template and the guidelines

The structure above is the template, `prd.template.md`, and the method is the
`etabli-spec` skill itself. Both ship with the kit, under
`.agents/skills/etabli-spec/`, and the agent follows them without you doing
anything. You can read the
[template](https://github.com/ancelin-code/etabli/blob/main/.agents/skills/etabli-spec/assets/prd.template.md)
and the
[skill](https://github.com/ancelin-code/etabli/blob/main/.agents/skills/etabli-spec/SKILL.md)
on GitHub.
