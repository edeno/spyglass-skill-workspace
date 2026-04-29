# Adding 3 more CA1 tetrodes to ripple detection: what re-populates?

Short answer: in DataJoint, a downstream Computed table re-populates only
when one of its primary-key parents gets a new key (or when an upstream key
it depends on is deleted and re-inserted). So the question reduces to: which
tables in the ripple chain take the electrode set into their primary key?

I'll walk the chain from raw recording down to ripple times, then call out
what is and isn't affected.

## The ripple chain (from upstream to downstream)

Roughly, with the electrode-bearing tables in **bold**:

1. `Electrode` (per-session electrode metadata, common schema)
2. **`LFPElectrodeGroup`** (Manual) + `LFPElectrodeGroup.LFPElectrode` (Part)
   - This is the user-defined group of electrodes whose raw data gets LFP'd.
3. `LFPSelection` (Manual) -> `LFPV1` (Computed)
   - Wide-band LFP for the chosen `LFPElectrodeGroup`.
4. **`LFPBandSelection`** (Manual) + `LFPBandSelection.LFPBandElectrode` (Part)
   -> `LFPBandV1` (Computed)
   - The ripple-band (~150-250 Hz) filtered subset. The Part table picks
     *which* electrodes from the LFPElectrodeGroup get band-filtered.
5. **`RippleLFPSelection`** (Manual) + `RippleLFPSelection.RippleLFPElectrode`
   (Part) -> `RippleTimesV1` (Computed)
   - Picks *which* of the band-filtered electrodes are used for ripple
     detection (typically the CA1 pyramidal-layer subset).
6. `RippleParameters` (Lookup) is also a parent of `RippleTimesV1`, but
   it's not electrode-dependent.

## What changes when you add 3 more CA1 tetrodes

The answer depends on whether those tetrodes' channels are *already*
represented at each upstream level. Three cases, from most to least common:

### Case A: new tetrodes already in `LFPElectrodeGroup` and `LFPBandSelection.LFPBandElectrode`

This is the typical setup if you originally band-filtered all CA1
candidates and only narrowed the set at the ripple-detection step.

Affected:
- **`RippleLFPSelection.RippleLFPElectrode`** — you insert (or replace) rows
  to add the 3 new tetrodes' electrode IDs. If the parent
  `RippleLFPSelection` row's primary key (which is essentially
  `LFPBandV1` key + `group_name`) is unchanged, you're modifying the
  Part-table membership of an existing selection.
- **`RippleTimesV1`** — re-populates. This is the table that actually
  recomputes the ripple times using the augmented electrode set.
  Important caveat: because you're modifying a Part table, DataJoint will
  *not* automatically invalidate the existing `RippleTimesV1` row. You
  typically need to `(RippleTimesV1 & key).delete()` the old row first,
  then `RippleTimesV1.populate(key)` to recompute. Otherwise the
  downstream row will silently still reflect the old electrode list.
  (If you instead create a *new* `RippleLFPSelection` entry with a
  different `group_name`, you'll get a fresh `RippleTimesV1` row alongside
  the old one.)

Unaffected:
- `LFPElectrodeGroup`, `LFPElectrode`, `LFPSelection`, `LFPV1`,
  `LFPBandSelection`, `LFPBandSelection.LFPBandElectrode`, `LFPBandV1`.
  None of them depend on `RippleLFPSelection`.

### Case B: new tetrodes in `LFPElectrodeGroup` but NOT in `LFPBandSelection.LFPBandElectrode`

Affected (in addition to Case A):
- **`LFPBandSelection.LFPBandElectrode`** — needs new rows for the 3
  tetrodes' electrodes against the ripple filter. This may require a new
  `LFPBandSelection` entry (since the Part-table membership defines the
  band-filtered set).
- **`LFPBandV1`** — re-populates for the new selection so that the new
  electrodes have band-filtered traces available. As above, modifying a
  Part table doesn't auto-invalidate the existing `LFPBandV1` row, so you
  may need to delete and re-populate, or create a new selection key.
- Then `RippleLFPSelection` and `RippleTimesV1` follow as in Case A.

Still unaffected: `LFPElectrodeGroup`, `LFPSelection`, `LFPV1` (the
wide-band LFP already covers those channels because they are in the
electrode group).

### Case C: new tetrodes NOT in `LFPElectrodeGroup` at all

Affected (in addition to Case B):
- **`LFPElectrodeGroup.LFPElectrode`** — needs new entries for the
  tetrodes' channels.
- **`LFPSelection` -> `LFPV1`** — needs (re-)populating so that the 3
  new tetrodes have wide-band LFP at all. In practice this usually means
  defining a new electrode group, because changing membership of an
  existing one is messy and cascade-deletes everything downstream.

So at the limit, adding tetrodes that were never in your LFP group at all
forces a re-run of the entire LFP -> LFP-band -> ripple chain.

## What is unaffected in all cases

- **`RippleParameters`** — this is a `dj.Lookup` table holding parameter
  *names* and parameter dicts (z-score thresholds, smoothing sigma, etc.).
  It has no electrode dependency, so changing the electrode set does
  nothing to it. The same `ripple_param_name` row continues to apply.
- **Position pipelines** (`PositionOutput`, Trodes/DLC pos sources). These
  feed into `RippleTimesV1` (it consumes head/animal speed) but they
  don't depend on the electrode selection. They're already populated
  for your session; nothing about them re-runs.
- **Spike sorting pipeline** (`SpikeSortingSelection`, `CurationV1`,
  sorted spikes, etc.). Independent branch; ripples don't feed back into
  it.
- **Decoding pipelines** (`SortedSpikesDecodingV1`,
  `ClusterlessDecodingV1`, etc.). These don't directly depend on
  `RippleTimesV1` keys. They will be unaffected unless your downstream
  analysis explicitly restricts decoded posteriors to ripple times — and
  even then, the *decoding* table itself doesn't re-populate; only your
  ad-hoc analysis that joins ripples to decoding output would see the new
  ripple set.
- **Anything not on the directed path downstream of `RippleTimesV1`.**
  In DataJoint terms: only `RippleTimesV1.descendants()` are at risk, and
  in core Spyglass that descendant set is essentially empty (downstream
  use of ripple times is typically done in user analysis code, not in
  another Computed table).

## Practical recipe

1. Confirm which case you're in:

   ```python
   from spyglass.lfp.lfp_electrode import LFPElectrodeGroup
   from spyglass.lfp.analysis.v1.lfp_band import LFPBandSelection
   key = {...}  # your nwb_file_name + lfp_merge_id + filter_name + interval

   in_group = (LFPElectrodeGroup.LFPElectrode & key).fetch("electrode_id")
   in_band  = (LFPBandSelection.LFPBandElectrode & key).fetch("electrode_id")
   ```

   If the 3 new tetrodes' electrode IDs are in `in_band`, you're in
   Case A. If they're in `in_group` but not `in_band`, Case B. Otherwise
   Case C.

2. For Case A:

   ```python
   from spyglass.ripple.v1.ripple import RippleLFPSelection, RippleTimesV1

   # Drop the stale ripple times so populate() will recompute.
   (RippleTimesV1 & ripple_key).delete()

   # Update the Part-table membership.
   RippleLFPSelection.set_lfp_electrodes(
       ripple_key,
       electrode_list=old_list + new_tetrode_electrode_ids,
       group_name="CA1",
   )

   RippleTimesV1.populate(ripple_key)
   ```

3. For Cases B/C: extend upstream (LFP-band, or the LFP electrode group)
   first, re-populate `LFPBandV1` (and `LFPV1` if needed), then proceed
   as in Case A. Be aware of cascade deletes if you modify existing
   selection rows rather than creating new ones.

## Caveats / things I'd verify

- I'm reasoning from the schema topology (`LFPElectrodeGroup` ->
  `LFPBandSelection`/`LFPBandElectrode` -> `LFPBandV1` ->
  `RippleLFPSelection`/`RippleLFPElectrode` -> `RippleTimesV1`) and from
  general DataJoint semantics. If your Spyglass version has additional
  downstream tables that consume `RippleTimesV1` (e.g. a ripple-content
  decoding table, or a custom merge-table entry), those would also need
  re-population — check `RippleTimesV1.descendants(as_objects=True)` in
  your install to confirm.
- DataJoint does *not* automatically detect Part-table membership
  changes as invalidating downstream Computed entries. Always `delete()`
  the stale `RippleTimesV1` (and `LFPBandV1` if applicable) row before
  `populate()`, or create a new selection key. Skipping this step is the
  most common way to silently end up with ripple times computed against
  the old electrode list.
- Whether you should *modify* an existing `RippleLFPSelection`/
  `LFPBandSelection` entry or create a *new* one is a workflow question:
  modifying loses the old result; creating a new key with a different
  `group_name` (e.g. `"CA1_extended"`) keeps both versions side by side
  and makes the change auditable. The latter is usually preferable for
  research records.
