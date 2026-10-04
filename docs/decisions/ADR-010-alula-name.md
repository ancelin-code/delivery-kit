# ADR-010: The kit is named Alula

**Status:** accepted
**Date:** 2026-10-04
**Supersedes:** the name and metaphor in [ADR-006](ADR-006-fourmee-name-and-identifiers.md)
**Partly superseded by:** [ADR-011](ADR-011-skill-names.md), for the skill names

## Context

[ADR-006](ADR-006-fourmee-name-and-identifiers.md) named the kit *Fourmee*, an
invented spelling of the French *fourmi*, ant. Two days later its author found
they did not like it: an invented spelling of a French word reads as a gimmick,
and the ant metaphor was carried by the name alone. Nothing was public, so
changing it cost one rename and no migration.

The kit's author also trades as ALDEA, *Atelier Logiciel du Dauphiné et des
Alpes*. A name with a Latin or Romance root sits next to it better than an
English pun does.

## Decision

**The name is Alula.**

*Alula* is Latin, a diminutive of *ala*, wing: literally "little wing". It is
also the anatomical term for the small group of feathers on a bird's leading
edge, sometimes called the bastard wing. A bird raises it when it flies slowly,
at a steep angle, which is when the main wing would stall. The alula keeps the
air attached to the wing at that moment, so the bird can slow down and land
instead of dropping. Aircraft have a mechanical equivalent, the leading-edge
slat, which works on the same principle.

### How it relates to the project

- **A small part that matters in the hard moment.** The alula adds almost
  nothing in cruise and is what prevents the stall. This kit is the same in a
  delivery: a few scripts and rules that cost little when the work is easy and
  keep parallel lanes from stalling when it is not, with claims that cannot be
  taken twice, a validated task set, and gates where a human decides.
- **It manages flow at the edge.** The alula does not make the wing; it keeps
  the airflow orderly where it would break away. Alula does not write the code
  or choose the model. It keeps the work moving in order around the agents that
  do.
- **Wings fly in parallel.** The lanes are parallel work that has to stay
  coordinated, which a wing is the picture of.
- **It is unglamorous on purpose.** Nobody names a product after a slat. That
  is the tagline, *Boring on purpose*: the kit earns its place only by what it
  prevents.
- **It sits beside ALDEA.** Latin root, and the shared first letters.

Stigmergy, the coordination through marks left in a shared environment that
ADR-006 used as the metaphor, stays a design fact: claims are branches in git,
and status is read from refs. It is no longer the brand.

Trending words such as *agent* or *orchestrator* still stay out of the name.
They belong in the tagline, the description and the repository topics.

### What changes

| Before | After |
|---|---|
| `fourmee`, `fourmee-spec`, `-decompose`, `-implement`, `-status` | `alula`, `alula-spec`, `alula-decompose`, `alula-implement`, `alula-status` |
| `FOURMEE_*` variables | `ALULA_*` |
| `<!-- fourmee:routing -->` marker | `<!-- alula:routing -->` |
| `product-version: fourmee@v0` | `alula@v0` |
| `ancelin-code/fourmee` | `ancelin-code/alula` |

The `delivery/` directory keeps its name, as ADR-006 decided. The entry point
reads `/alula what's next`.

## Alternatives considered

Each was checked on 2026-10-04 for a GitHub repository of the same name, the
npm and PyPI names, and whether a `.dev` domain looked taken.

- **Tarmac**, the author's first choice. Heavily used: a 345-star
  WebAssembly framework, the npm and PyPI names taken, the `.dev` domain on
  sale, and a well-known building-materials company of the same name.
- **Lasius**, the ant genus. A fitting meaning, since *Lasius niger* is the most
  ordinary garden ant, but a similarly named time-tracking project exists, the
  `.dev` domain is taken, and nobody agrees how to say it.
- **Piazzale**, Italian for the airport apron and for a public square. The
  closest to Tarmac, and free everywhere checked. Passed over for the story
  and the pronunciation of Alula.
- **Cordée**, a roped climbing party, which says Alps and parallel members who
  anchor in turn. Free everywhere checked. Not aviation.
- **Hardstand**, the plainest aircraft parking term. Free, English only.
- **Balise**, a beacon, close to the marks idea. An npm package and a
  repository exist, and the `.dev` domain is taken.
- **Velivolo, Rodaje, Envol, Escale, Bitume** and others, set aside as hard to
  say, too generic, or already used on PyPI.

## Consequences

- The names above are a snapshot. The npm and PyPI names and the `.dev` domain
  looked free; a personal GitHub account called `alula` exists and holds a
  small unrelated repository. The project lives under `ancelin-code`, so the
  account does not conflict, but `github.com/alula` is not available as an
  organisation.
- **Not checked, and the author's to do:** a trademark search for *Alula* in
  EUIPO and USPTO, software classes 9 and 42, and a registrar check of the
  `.dev` domain, since only DNS was looked at.
- A project that installed the kit under the old names must reinstall and
  re-run `install-routing.sh`. No public installation exists, so nothing is
  migrated.
- Earlier decision records keep their reasoning and use the new names, except
  ADR-006, which is left as written because it records the name this replaced.
