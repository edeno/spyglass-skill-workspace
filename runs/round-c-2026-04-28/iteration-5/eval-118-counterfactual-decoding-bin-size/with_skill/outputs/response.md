# Changing `position_bin_size` in `DecodingParameters` — what cascades

## First, a correction on the field name

`DecodingParameters` does **not** have a top-level `position_bin_size` attribute. Its definition is just three columns (`src/spyglass/decoding/v1/core.py:38-43`):

```text
decoding_param_name : varchar(80)   # PK
---
decoding_params  : LONGBLOB         # model init kwargs (the blob you'd edit)
decoding_kwargs  = NULL : LONGBLOB  # runtime kwargs
```

`position_bin_size` lives **inside the `decoding_params` blob** as a constructor kwarg passed through to the underlying `non_local_detector` classifier (e.g. `Environment(position_bin_size=2.0)`). So "change `position_bin_size` from 2 cm to 5 cm" really means "produce a new `decoding_params` blob with `position_bin_size=5.0` somewhere inside it." How you do that is decisive for what cascades, so I'll split the answer accordingly.

## Cascade structure (same regardless of which interpretation below)

Source: `src/spyglass/decoding/v1/clusterless.py:83-101` and the analogous `sorted_spikes.py`. The chain *downstream* of `DecodingParameters` is:

```
DecodingParameters
        |
        v
ClusterlessDecodingSelection           SortedSpikesDecodingSelection
        |                                       |
        v                                       v
ClusterlessDecodingV1 (Computed)       SortedSpikesDecodingV1 (Computed)
        |                                       |
        v                                       v
DecodingOutput.ClusterlessDecodingV1   DecodingOutput.SortedSpikesDecodingV1
        \_______________________________________/
                          |
                          v
                    DecodingOutput   (merge master)
```

Both selection tables FK directly to `DecodingParameters` via `decoding_param_name`. The Computed tables (where the posterior `.nc` files live) FK to their respective Selection tables. `DecodingOutput` is the merge master that part-tables both Computed tables.

You said you only care about the decoding posterior, so the relevant rows on that chain are:

- `ClusterlessDecodingSelection` / `SortedSpikesDecodingSelection` rows that name your edited `decoding_param_name`
- `ClusterlessDecodingV1` / `SortedSpikesDecodingV1` rows produced from those selections (these hold `results_path` — the `.nc` file with the posterior)
- The corresponding `DecodingOutput` part-table rows (one `merge_id` per Computed row)

Nothing else in Spyglass depends on `DecodingParameters`.

## What actually changes — depends on how you "change" it

### Interpretation 1: you edit an existing row in place

DataJoint primary-keyed rows aren't really mutable. To change the blob on an existing `decoding_param_name`, you'd `.delete()` the row and reinsert with the new blob. The delete cascades destructively through every downstream row above:

- All `ClusterlessDecodingSelection` / `SortedSpikesDecodingSelection` rows referencing that `decoding_param_name` are deleted.
- All `ClusterlessDecodingV1` / `SortedSpikesDecodingV1` rows produced from those selections are deleted, and their `.nc` and `.pkl` files become orphaned on disk (they're cleaned up by `DecodingOutput().cleanup(dry_run=False)`, see `decoding_pipeline.md` § Storage).
- The corresponding `DecodingOutput` part rows go with them.
- After reinsert + `populate()`, you get **new** `merge_id`s for the regenerated posteriors — anything you'd cached (URLs, notebooks pinned to the old `merge_id`) breaks.

This is destructive on irreplaceable computed results and is gated by `cautious_delete` (Core Directive #1 in SKILL.md). Do **not** do this without the inspect-before-destroy loop:

```python
target = (DecodingParameters & {'decoding_param_name': name})
# Preview cascade
target.delete(safemode=True)   # interactive prompt; inspect what it'll drop
```

### Interpretation 2: you create a new `DecodingParameters` row (recommended)

Insert a new row with a new name (e.g. `'contfrag_clusterless_bin5cm'`) carrying the 5-cm-binned blob. Then either:

- Build a **new** `ClusterlessDecodingSelection` row with `decoding_param_name='contfrag_clusterless_bin5cm'` and call `populate()`, or
- Leave existing selection rows alone.

Cascade in this case:

- **Existing** `ClusterlessDecodingV1` / `SortedSpikesDecodingV1` rows do not change. Their posteriors still reflect the 2-cm bin. Their `merge_id`s in `DecodingOutput` are untouched.
- The new selection row produces a **new** `ClusterlessDecodingV1` / `SortedSpikesDecodingV1` row, and a corresponding new `DecodingOutput` part row with a fresh `merge_id`. That new posterior is what reflects the 5-cm bin.

This is the path I'd recommend — it preserves provenance, avoids cascading deletes on computed results, and lets you compare 2-cm vs 5-cm posteriors side-by-side using the two `merge_id`s.

## Caveat — no source confirmation that `position_bin_size` is consumed

I confirmed the table cascade structure from Spyglass source. I did **not** find any reference to `position_bin_size` in `src/spyglass/decoding/` (`grep -rn "position_bin_size" src/spyglass/decoding/` returns no hits) — Spyglass passes `decoding_params` opaquely to the `non_local_detector` constructor (`clusterless.py:113-119`), so whether `position_bin_size` is honored, where it lives in the nested blob (top-level vs nested under an `Environment` config), and what units it expects depend on the installed `non_local_detector` version. Verify with `inspect.signature` against the classifier you're using, and look at one of the default-shipped rows to see the existing key path:

```python
(DecodingParameters & {'decoding_param_name': f'contfrag_clusterless_{non_local_detector_version}'}).fetch1('decoding_params')
```

before assuming `position_bin_size` is the right kwarg name to flip.

## TL;DR

- `position_bin_size` is not a `DecodingParameters` column; it's nested inside the `decoding_params` blob and consumed by `non_local_detector`.
- The downstream chain that holds the posterior is: `*DecodingSelection` → `*DecodingV1` (computed, owns `results_path`) → `DecodingOutput.*DecodingV1` (merge part) → `DecodingOutput` (merge master). Nothing else depends on `DecodingParameters`.
- Changing the row in place cascades a destructive delete through every populated posterior using that `decoding_param_name` — paired `.nc`/`.pkl` files on disk become orphans.
- Inserting a new row with a new name leaves existing posteriors untouched; only the rows you populate against the new name carry the 5-cm bin. Strongly preferred.
