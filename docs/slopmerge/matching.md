# Matching

## Normalisation levels

Functions and blocks are reduced to a sequence of normalised statements at
three levels.

| Level | Ignores | Keeps |
|---|---|---|
| **N0** (exact) | Formatting, comments, docstrings, annotations. | Everything else. |
| **N1** (renamed) | Local names, literal values. | Attribute names, called names, operators, control flow. |
| **N2** (vocabulary) | Statement structure and order. | A bag of calls, attributes, imported modules, string literals, exceptions raised/caught. |

Keeping what's *called* at N1 means `x.append(y)` and `x.update(y)` don't
match.

A statement contributes only its own header: an `if` adds its test, and its
body's statements follow in order. That keeps sequences comparable when code
has been re-nested.

## Scoring

`near` score of two functions or blocks, from their N1 sequences:

```
sim(a, b) = 2 · W(LCS(a, b)) / (W(a) + W(b))
```

`LCS` is the longest common subsequence, so order matters. `W` sums
**IDF weights**: a statement that appears everywhere (`self.x = x` in 400
`__init__`s) weighs about 1; a rare one weighs several times more. Weights
are computed over distinct shapes, so a function copied ten times doesn't
discount its own statements. The IDF is smoothed so tiny inputs still work.

`related` uses the same idea on the N2 token bags: weighted overlap
`2 · W(shared) / (W(a) + W(b))`. It only compares functions that matched
nothing else, sharing 3+ tokens, within 2x of each other in size.

A member's `similarity` is its score against the group's medoid (below).
A group's `similarity` is the min and max of those.

## Grouping

Functions with equal N1 form share a **shape**; they're certain copies, so
shapes are what get scored. A shape with 2+ functions and no near
neighbours is an `exact` or `renamed` group.

For `near`, shape pairs scoring above the threshold form a graph, and
groups are its connected components. Two safeguards:

- **Chaining** (A~B, B~C, A and C unrelated): every shape must score above
  the threshold against the **medoid**, the shape most similar to the
  rest. Those that don't are split off and regrouped. The medoid is the
  natural "keep this one" candidate.
- **Nesting**: a function and one nested in it are never compared or
  grouped together.
