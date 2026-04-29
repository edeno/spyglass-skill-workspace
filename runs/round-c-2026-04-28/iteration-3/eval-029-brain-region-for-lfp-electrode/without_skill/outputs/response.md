# Brain region for an LFP electrode

Short answer: the brain region is **anatomical metadata that lives on `Electrode`**, not on anything in the LFP pipeline. Filtering a signal doesn't change where the contact was implanted, so you don't need the `LFPOutput` merge_id to answer this question — you just join `Electrode` against `BrainRegion` and restrict to the electrode you care about.

## The query

In Spyglass, `common.Electrode` has a foreign key to `common.BrainRegion` (declared via `-> BrainRegion` in the table definition), and `BrainRegion` carries the `region_name` attribute. So:

```python
from spyglass.common import Electrode, BrainRegion

key = {"nwb_file_name": "j1620210710_.nwb", "electrode_id": 7}

region_name = (Electrode * BrainRegion & key).fetch1("region_name")
print(region_name)
```

That's it. One join, one `fetch1`, one string. Use that string as your plot label.

If you also want the finer-grained fields, `BrainRegion` has `subregion_name` and `subsubregion_name` as well:

```python
(Electrode * BrainRegion & key).fetch1(
    "region_name", "subregion_name", "subsubregion_name"
)
```

## Why the LFP merge_id isn't in the picture

The chain at ingest is roughly:

- The NWB file's electrode group has a `location` string (set when the recording was prepared).
- `Electrode.make()` reads that, calls `BrainRegion.fetch_add(...)` to get/create a `region_id`, and stores it on the `Electrode` row.
- Everything downstream — `LFPElectrodeGroup`, `LFPV1`, `LFPOutput`, ripples, decoding, etc. — references electrodes by `(nwb_file_name, electrode_group_name, electrode_id)`. None of those tables override or recompute the region; they just point back to the same `Electrode` row.

So `LFPV1`, `LFPOutput`, and the merge entry have **no `region` attribute of their own**. Don't go looking for one — you'll either not find it or, worse, find something that looks like one and isn't (e.g. an electrode group name that happens to be CA1-ish but isn't the curated region label). Always go through `Electrode * BrainRegion`.

## Optional: verify electrode 7 was actually in the LFP group

You said you already have the merge_id, so I'll mention this in case it's useful — but it's a separate question from "what region?". If you also want to confirm electrode 7 was one of the channels included in the wideband LFP for that merge entry (not just that it exists on the probe), you'd:

1. Resolve the merge_id back to its source key (typically via `LFPOutput.merge_get_parent(...)` / the merge-table machinery, which gives you the `LFPV1` selection key).
2. Restrict `LFPElectrodeGroup.LFPElectrode` (the part table that lists the channels in the LFP electrode group) by that selection key, and check that `electrode_id=7` is present.

But that's an inclusion check, not a region lookup. The region itself comes from `Electrode * BrainRegion` regardless.

## What not to do

- Don't query `LFPV1` or `LFPOutput` for a `region` — there isn't one.
- Don't infer the region from the LFP filter parameters or sampling rate; those describe the signal, not the anatomy. The wideband-vs-decimated distinction has nothing to do with where the wire is.
- Don't `fetch()` (plural) without restricting to a single electrode — you'll get every electrode in the session and have to find row 7 by hand. `fetch1` with a fully-specified key is the clean form here.
