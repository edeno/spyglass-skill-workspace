# Next step after inserting an `LFPSelection` row

The next step is **`LFPV1.populate(key)`** — the selection row is just the spec; `LFPV1` is the computed table that actually does the FIR filtering and writes the filtered LFP to an analysis NWB file (source: `spyglass/lfp/v1/lfp.py`, referenced in [`references/lfp_pipeline.md`](../../../../spyglass/references/lfp_pipeline.md)).

## Minimal flow

```python
from spyglass.lfp import LFPOutput
from spyglass.lfp.v1 import LFPV1

# `key` is the same dict you just inserted into LFPSelection
LFPV1.populate(key)

# After populate succeeds, fetch via the merge layer:
merge_key = LFPOutput.merge_get_part(key).fetch1("KEY")
lfp_df = (LFPOutput & merge_key).fetch1_dataframe()
```

## What `populate()` actually does

`LFPV1.make()` reads your selection row, fetches the matching FIR filter from `FirFilterParameters` keyed on `(filter_name, filter_sampling_rate)`, applies it to `Raw`, downsamples to `target_sampling_rate`, and inserts a row into `LFPV1` plus a part-table entry under `LFPOutput.LFPV1` so downstream pipelines can reference the result via the merge table.

## Before you run it — two correctness checks worth doing

These are the gates that catch the most common LFPSelection-stage mistakes (see [`references/lfp_pipeline.md` Step 2](../../../../spyglass/references/lfp_pipeline.md) and the Nyquist note there):

1. **Confirm `filter_sampling_rate` matches the actual raw rate.** `LFPV1.make()` looks up the FIR filter by `(filter_name, filter_sampling_rate)`; a 30 kHz filter row won't apply to a 20 kHz recording. Derive it rather than hard-coding:
   ```python
   import numpy as np
   from spyglass.common import Raw
   raw_rate = int(np.round(
       (Raw & {"nwb_file_name": key["nwb_file_name"]}).fetch1("sampling_rate")
   ))
   assert key["filter_sampling_rate"] == raw_rate
   ```

2. **Confirm `target_interval_list_name` exists.** It's a foreign key into `IntervalList`; if it doesn't exist the `insert1` would already have raised, but if you used `skip_duplicates=True` and want to verify the selection is what you expect:
   ```python
   print(len(LFPSelection & key))   # should be 1
   ```

## Restrict populate to your row

`LFPV1.populate(key)` with the full selection key restricts work to just this entry — much safer than calling `LFPV1.populate()` bare, which would try to populate every outstanding `LFPSelection` row in the database.

## After it succeeds — what's downstream

Depending on your goal:

- **Just want the filtered broadband LFP as a DataFrame** → `LFPOutput.merge_get_part(key).fetch1("KEY")` then `(LFPOutput & merge_key).fetch1_dataframe()`. Done.
- **Want theta phase / power, ripple-band, or any narrowband analysis** → next step is `LFPBandSelection` + `LFPBandV1` (Step 4 in the LFP reference). `LFPBandSelection` FKs `LFPOutput.proj(lfp_merge_id='merge_id')`, so you grab the merge_id from the merge table, register a band filter via `FirFilterParameters().add_filter(...)` at `fs=1000` (the LFP's `target_sampling_rate`), and call `LFPBandSelection().set_lfp_band_electrodes(...)`.
- **Want ripple detection** → populate a ripple-band `LFPBandV1` (filter name must contain `"ripple"`; `RippleLFPSelection.validate_key` enforces this), then move into the ripple pipeline.
- **Want artifact-cleaned intervals** → optional `LFPArtifactDetectionSelection` + `LFPArtifactDetection` (Step 3); note this FKs `LFPV1` directly, **not** `LFPOutput` — pass the LFPSelection PK fields, not a merge key.

## Verifying the populate worked

```python
print(len(LFPV1 & key))                          # expect 1
print(len(LFPOutput.LFPV1 & key))                # expect 1 (part-table entry)
LFPOutput.merge_get_part(key).fetch1("merge_id") # expect a UUID
```

If `LFPV1 & key` is empty after `populate()`, check the `populate()` stdout/exception — common causes are a missing `IntervalList` row, a `FirFilterParameters` row missing for `(filter_name, filter_sampling_rate)`, or a Raw sampling-rate mismatch.

## Source references

- Canonical example and pipeline flow: `/Users/edeno/Documents/GitHub/spyglass-skill/skills/spyglass/references/lfp_pipeline.md`
- `LFPV1.make()` filter lookup: `spyglass/lfp/v1/lfp.py:72-75, 107-109` (cited in the skill reference; verify against your installed version with `python -c "import spyglass, os; print(os.path.dirname(spyglass.__file__))"`)
- `FirFilterParameters.create_standard_filters()`: `spyglass/common/common_filter.py:577`
