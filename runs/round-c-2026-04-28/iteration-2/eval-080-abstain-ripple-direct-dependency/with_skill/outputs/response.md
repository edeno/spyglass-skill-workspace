# Does `RippleTimesV1` directly depend on `LFPV1`?

**Short answer: No, not directly — but a `cautious_delete` of an `LFPV1` row will still cascade into your `RippleTimesV1` rows via an indirect chain through the LFP-band layer and the merge table. Don't run the delete until you've inspected the actual cascade scope for *this specific row*.**

## The direct parents of `RippleTimesV1`

From `src/spyglass/ripple/v1/ripple.py:182-186`, `RippleTimesV1`'s definition declares **three** direct foreign keys (plus `AnalysisNwbfile`):

```python
@schema
class RippleTimesV1(SpyglassMixin, dj.Computed):
    definition = """
    -> RippleLFPSelection
    -> RippleParameters
    -> PositionOutput.proj(pos_merge_id='merge_id')
    ---
    -> AnalysisNwbfile
    ...
    """
```

So the direct parents are:

1. `RippleLFPSelection`
2. `RippleParameters`
3. `PositionOutput` (projected as `pos_merge_id`)

`LFPV1` is **not** in that list. It is reachable only indirectly.

## How `LFPV1` actually reaches `RippleTimesV1` (the indirect chain)

Walking upstream from `RippleTimesV1`:

- `RippleLFPSelection` (`ripple/v1/ripple.py:33-35`) declares `-> LFPBandV1` as its master FK.
- Its part table `RippleLFPSelection.RippleLFPElectrode` (`ripple/v1/ripple.py:39-42`) additionally declares `-> LFPBandSelection.LFPBandElectrode`.
- `LFPBandV1` (`lfp/analysis/v1/lfp_band.py:290-292`) is keyed on `LFPBandSelection`.
- `LFPBandSelection` (`lfp/analysis/v1/lfp_band.py:22-26`) declares `-> LFPOutput.proj(lfp_merge_id='merge_id')` — i.e. it FKs the `LFPOutput` *merge master*, not `LFPV1` directly.
- `LFPOutput` (`lfp/lfp_merge.py:16-25`) is the merge master; its part `LFPOutput.LFPV1` (`lfp/lfp_merge.py:23-25`) carries `-> LFPV1`.

So the actual cascade path from a single `LFPV1` row down to `RippleTimesV1` is:

```
LFPV1
  → LFPOutput.LFPV1            (the merge part that points at this LFPV1 row)
  → LFPBandSelection           (FKs LFPOutput via lfp_merge_id; pulls in any LFPBand selections built off this LFP)
  → LFPBandV1                  (computed downstream of LFPBandSelection)
  → RippleLFPSelection         (FKs LFPBandV1; selection rows built off that LFPBand)
  → RippleTimesV1              (FKs RippleLFPSelection)
```

Cascades don't stop at intermediate tables. If `LFPBandV1` was populated off the `LFPV1` row you're about to delete, every `RippleTimesV1` row that lives downstream of that `LFPBandV1` selection will also disappear. So in practice the answer to "will the delete take out my ripple times" is **probably yes, indirectly** — but only if downstream LFP-band / ripple-LFP-selection / ripple-times rows actually exist for this particular `LFPV1` row. That is a runtime question about your specific row, not a static-graph question.

## Don't trust the graph from memory — inspect the actual cascade

Before any `cautious_delete`, get DataJoint to tell you what the cascade scope actually is for *this row*. Two complementary primitives:

```python
# 1. Static dependency graph: what tables descend from LFPV1 in source?
from spyglass.lfp.v1.lfp import LFPV1
LFPV1.descendants()                    # table NAMES of every downstream table
# or, for objects you can restrict / count:
LFPV1.descendants(as_objects=True)

# 2. The cascade scope for THIS specific row:
key = {... your LFPV1 PK ...}
target = (LFPV1 & key)
print(len(target))                     # must be 1 for a "single row" delete
# Walk descendants and count rows that would actually go:
for child in LFPV1.descendants(as_objects=True):
    n = len((child * target) if False else (child & target.fetch1("KEY")))
    # or use child.restrict(...) appropriately for your child's PK shape
    print(child.full_table_name, n)
```

For the topology view (and what `RippleTimesV1` itself sees as parents), you can also use:

```python
RippleTimesV1.parents()                # direct parents only (one hop)
import datajoint as dj
dj.Diagram(RippleTimesV1) - 3 + 1      # neighborhood diagram
```

The skill bundles a CLI that does this against either the source graph or the live DB:

```bash
# source-only (no DB required):
python skills/spyglass/scripts/code_graph.py parents RippleTimesV1
python skills/spyglass/scripts/code_graph.py path --down LFPV1

# runtime (against the connected DB, restriction-aware row counts):
python skills/spyglass/scripts/db_graph.py path --down LFPV1
```

`parents()` answers the literal question you asked ("is `LFPV1` directly above `RippleTimesV1`?" — no, the three names above are). `descendants()` plus row counts on the restricted relation answers the question you actually care about ("will my ripple times go away?").

## Workflow before you run the delete

This is a destructive operation against irreplaceable data, so route it through the inspect-before-destroy workflow in [destructive_operations.md](../../../../skills/spyglass/references/destructive_operations.md). The required phases are:

1. **Inspect** — build the restricted relation and `print(len(target))`. Enumerate descendants and count rows that would cascade. If any count is unexpectedly large (e.g. you thought you were touching one ripple-times row and it's about to take out 40), stop.
2. **Report** — show me the row count, sample rows, and the per-descendant cascade counts before asking me to confirm.
3. **Wait for explicit confirmation** — "yes, delete" or equivalent, after you've seen Phase 2's output.
4. **Execute** — `target.delete()` (which on `SpyglassMixin` aliases to `cautious_delete` and runs the team-permission check).
5. **Verify** — re-count the relevant tables after to confirm only the intended rows are gone.

A couple of additional notes specific to this delete:

- Because the chain runs through `LFPOutput` (a merge master), the delete will propagate via the `LFPOutput.LFPV1` part. That's the normal merge-table cascade behavior — no special `merge_delete` needed for a `cautious_delete` on the upstream `LFPV1` row.
- If `cautious_delete` raises `PermissionError`, that's the team-based protection working — it means another lab member owns the session(s) attached to this row. Coordinate with them; don't reach for `super_delete()` or `force_permission=True` (see [destructive_operations.md § Team-based protection](../../../../skills/spyglass/references/destructive_operations.md#team-based-protection-delete-is-cautious_delete)).

## Bottom line

- `LFPV1` is **not** a direct parent of `RippleTimesV1`. The three direct parents are `RippleLFPSelection`, `RippleParameters`, and `PositionOutput` (projected as `pos_merge_id`).
- It is, however, an *indirect* upstream via `LFPOutput → LFPBandSelection → LFPBandV1 → RippleLFPSelection`, so the cascade can still reach `RippleTimesV1` if intermediate rows exist.
- Before deleting, run `RippleTimesV1.parents()` / `LFPV1.descendants()` (or `code_graph.py` / `db_graph.py`) and count rows on each downstream table restricted by your specific `LFPV1` key. Report counts to me, get explicit confirmation, *then* call `.delete()`. I'm not going to commit to a yes/no on the cascade scope from memory — that has to come from the inspect step on your row.
