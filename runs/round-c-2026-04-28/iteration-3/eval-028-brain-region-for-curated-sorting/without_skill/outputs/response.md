# Brain regions for a curated sorting in `CurationV1`

Without having Spyglass's schema in front of me I'll reason from the
DataJoint conventions used by the Frank-lab pipeline. Treat the exact
class names below as hypotheses to verify by running `dj.Diagram` on the
relevant schemas (`spyglass.spikesorting.v1` and
`spyglass.common.common_ephys` / `common_region`).

## Mental model

`CurationV1` identifies a *curation* of a *sorting*, and a sorting was
produced from a *recording* assembled from a *sort group* (typically a
tetrode or a group of probe channels). Brain region is **not** a property
of a unit or of a curation — it lives on the electrodes that fed into the
sort group. So the answer to "what brain regions are in this sorting" is
really "what regions do the electrodes in each sort group of this
recording belong to".

The path you're walking is roughly:

```
CurationV1
  -> SpikeSortingSelection           (which recording produced this sorting)
  -> SpikeSortingRecording / SpikeSortingRecordingSelection
                                     (which sort group(s) make up the recording)
  -> SortGroup.SortGroupElectrode    (which electrodes are in each sort group)
  -> Electrode                       (per-electrode metadata, incl. region key)
  -> BrainRegion                     (region_name, subregion_name, etc.)
```

`unit_id` does not enter this walk — every unit in a given sort group
shares the same set of electrodes, so all units in a sort group map to
the same set of regions.

## Explicit FK walk (recommended)

```python
from spyglass.spikesorting.v1 import (
    CurationV1,
    SpikeSortingSelection,
    SpikeSortingRecordingSelection,
)
from spyglass.common import SortGroup, Electrode, BrainRegion

key = {
    "sorting_id": "003581ca-a7e4-4953-bfc3-42198c1ba2a8",
    "curation_id": 0,
}

regions = (
    (CurationV1 & key)
    * (SpikeSortingSelection & key).proj("recording_id")
    * SpikeSortingRecordingSelection
    * SortGroup.SortGroupElectrode
    * Electrode
    * BrainRegion
).fetch("sort_group_id", "electrode_id", "region_name", as_dict=True)
```

Two notes on the join shape:

1. `SpikeSortingSelection` and `SpikeSortingRecordingSelection` both
   carry `recording_id` as a secondary attribute, and DataJoint refuses
   to join two tables that share a non-primary attribute name unless you
   project it onto one side. The `.proj("recording_id")` call (or
   equivalently splitting into two restrictions — fetch
   `recording_id` first, then restrict the next join by it) avoids that
   refusal.
2. The exact name of the part table (`SortGroup.SortGroupElectrode`),
   the linking selection table, and the electrode FK to `BrainRegion`
   should be confirmed against your installed Spyglass — these are the
   conventional names but small renames happen between versions.

A two-step equivalent that sidesteps the projection question:

```python
recording_id = (SpikeSortingSelection & key).fetch1("recording_id")
regions = (
    SpikeSortingRecordingSelection
    * SortGroup.SortGroupElectrode
    * Electrode
    * BrainRegion
    & {"recording_id": recording_id}
).fetch("sort_group_id", "electrode_id", "region_name", as_dict=True)
```

For a typical tetrode sort group all four electrodes are targeted to the
same region, so wrapping the result in `set(...)` or
`np.unique(...)` will collapse to one region per sort group. For
polymer probes (Neuropixels-style) a single sort group can in principle
span multiple regions if the channel grouping crosses an anatomical
boundary, and you want every electrode's region back, not just one.

## Convenience helper — and its caveat

`CurationV1` exposes a helper that returns sort-group-level metadata
joined to `BrainRegion` (commonly named `get_sort_group_info` on the
table). It's convenient — something like
`CurationV1.get_sort_group_info(key).fetch("region_name")` — but I'd
verify the implementation before relying on it for polymer-probe data,
because helpers of this shape often sample **one electrode per sort
group** (`limit=1`) and join that one electrode to `BrainRegion`. That
gives you one region per sort group, which is correct for tetrodes (all
electrodes co-located by lab convention) but **incomplete for sort
groups whose electrodes span multiple regions** — the helper will
silently report only the sampled electrode's region.

So:

- Tetrodes, all four channels in the same region: helper is fine, use
  whichever you prefer.
- Polymer-probe / multi-region sort groups: use the explicit FK walk
  above; do not trust the helper to enumerate all regions.

## What *not* to do

- Don't look for a `region` or `brain_region` attribute directly on
  `CurationV1` or on a unit row — it isn't there. Region lives on
  `Electrode`, reached through the sort group.
- Don't restrict by `unit_id`. All units in a sort group share
  electrodes, so `unit_id` doesn't change the regions you'd return.
- Don't assume `SpikeSortingSelection * SpikeSortingRecordingSelection`
  joins cleanly — project `recording_id` onto one side first, or split
  into two restrictions.

## How to verify on your install

```python
import datajoint as dj
from spyglass.spikesorting import v1 as ssv1
from spyglass.common import common_ephys, common_region

dj.Diagram(ssv1) + dj.Diagram(common_ephys) + dj.Diagram(common_region)
```

Confirm the FK chain SortGroup -> SortGroupElectrode -> Electrode ->
BrainRegion and the exact name of the selection table linking
`sorting_id` back to `recording_id` before pasting the query above into
production code.
