# Contract: <interface name>

**Status:** draft | agreed
**Parties:** <which lanes or components depend on this>

## Purpose

<One or two sentences: what crosses this boundary, and why.>

## Shape

<The definitive definition: schema, signature, or endpoint. Link an existing
specification instead of paraphrasing one.>

| Field | Type | Required | Meaning |
|---|---|---|---|
| `<name>` | `<type>` | yes / no | <meaning, and any constraint on the value> |

## Example

```text
<a concrete, valid instance>
```

## Error cases

| Condition | Result |
|---|---|
| <what can go wrong> | <what the caller observes> |

## Changing this contract

Lanes are building against this. A change needs agreement from every party
listed above, and the lanes must be told; a silent change produces work that
cannot be integrated.
