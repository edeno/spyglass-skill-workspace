# Does `RippleTimesV1` directly depend on `LFPV1`?

Short answer: I don't know the exact dependency graph from memory, and I don't want to guess on a question that gates a destructive `cautious_delete`. You should resolve this by inspecting the actual DataJoint dependency graph in your environment rather than trusting any answer (mine included) that isn't backed by the live schema.

## How to check directly (this is the authoritative answer)

DataJoint exposes the dependency graph on every table class. Run these in your usual Spyglass session:

```python
from spyglass.lfp.v1 import LFPV1
from spyglass.ripple.v1 import RippleTimesV1  # adjust import path to your version

# Direct parents of RippleTimesV1 — these are the tables it FK-references.
RippleTimesV1.parents()           # list of full table names
# or, easier to read:
RippleTimesV1().parents(as_objects=True)

# Direct children of LFPV1 — these are what cascade if you delete an LFPV1 row.
LFPV1.children()
LFPV1().children(as_objects=True)

# Full forward cascade for the *specific row* you're about to delete:
key = {...}  # the primary key of the LFPV1 row
(LFPV1 & key).descendants()       # everything a delete would touch

# And the upstream dependency chain RippleTimesV1 sits on:
RippleTimesV1.ancestors()

# Visual:
import datajoint as dj
dj.Diagram(LFPV1) + 2             # LFPV1 + 2 hops downstream
dj.Diagram(RippleTimesV1) - 3     # RippleTimesV1 + 3 hops upstream
```

`parents()` / `children()` give you the *direct* edges (one FK hop).
`ancestors()` / `descendants()` give you the *transitive* closure — which is what actually matters for cascade scope.

## What I can say from general knowledge of the Spyglass pipeline

I am fairly confident, but cannot verify here, that `RippleTimesV1` is **not** a direct child of `LFPV1`. The Spyglass ripple pipeline is layered roughly:

```
LFPV1
  → (LFP merge / LFPOutput)
    → LFPBandSelection / LFPBandV1   (band-pass filtered, e.g. 150–250 Hz)
      → RippleLFPSelection           (which electrodes to use for ripple detection)
        → RippleTimesV1              (also depends on RippleParameters, and a position table for speed gating)
```

So `LFPV1` is typically an *ancestor* of `RippleTimesV1`, but the direct FK parents of `RippleTimesV1` are the ripple-stage selection/parameter tables and a band-filtered LFP table (and usually a position table, since ripple detection gates on speed). That is enough for cascade purposes: deleting an `LFPV1` row will still propagate downstream through the merge → LFPBand → RippleLFPSelection → RippleTimesV1 chain *if* those downstream rows were populated from this `LFPV1` row. Indirect ≠ safe.

I want to flag this clearly: the exact set of direct parents of `RippleTimesV1` depends on the Spyglass version you have installed, and I'd rather you read it off `RippleTimesV1.parents()` than trust my recollection.

## Practical implication for your `cautious_delete`

Whether the parent edge is direct or indirect, the relevant question is "does the cascade reach my ripple times". The cascade follows transitive descendants, not just direct children, so:

1. Run `(LFPV1 & key).descendants()` for the specific row you plan to delete. That tells you exactly what will go.
2. If `RippleTimesV1` (or any `RippleTimes*` / `RippleLFP*` / `LFPBand*`) appears, the delete will take ripple-time rows with it.
3. If you want to keep ripple results, either re-key your downstream entries off a different LFP row first, or skip the delete.
4. Spyglass's `cautious_delete` will print the cascade preview before committing — read it; don't `y` through it.

If you have skill-side guidance on destructive deletes (something like a `destructive_operations.md` reference), follow that workflow rather than improvising — `cautious_delete` is recoverable in principle but expensive in practice once analysis files are gone.

## TL;DR

- I won't commit to "direct vs indirect" from memory on a question that controls a destructive op.
- Verify with `RippleTimesV1.parents()` and `(LFPV1 & key).descendants()` before deleting.
- My best recollection: not a *direct* parent, but reachable via the LFP-merge → LFPBand → RippleLFPSelection chain, so the cascade can still hit `RippleTimesV1`. Confirm in your session.
