# End-to-end flow: ingest → Trodes position → LFP → export

You're hitting four pipelines in sequence. I'll walk each one as its own step and call out every spot where you have to make a choice. Defaults that Spyglass actually ships are flagged as such; "you must pick" means there is no canonical default.

A piece of orientation that bites everyone the first time:

- You pass the **raw** filename (`j1620210710.nwb`) to `insert_sessions`. Spyglass copies the file and appends `_` before `.nwb` internally. **All downstream queries** (Session, IntervalList, Raw, LFPSelection, etc.) use the copy filename `j1620210710_.nwb`. Do not type the underscore yourself in step (1); do use it (or derive it via `get_nwb_copy_filename`) everywhere after.

```python
from spyglass.utils.nwb_helper_fn import get_nwb_copy_filename

nwb_file_name = "j1620210710.nwb"                          # what (1) takes
nwb_copy_file_name = get_nwb_copy_filename(nwb_file_name)  # "j1620210710_.nwb" — what (2)/(3)/(4) take
```

---

## (1) Ingest `j1620210710.nwb`

```python
import spyglass.data_import as sgi

sgi.insert_sessions("j1620210710.nwb")
```

Notes / choice points:

- **Filename convention.** Raw filename, no underscore. (`insert_sessions` itself adds the copy.)
- **Pre-inserts you may need before this call** if the NWB references hardware not already in the DB: `Lab`, `LabMember`, `Institution`, `ProbeType`, `Probe`, `DataAcquisitionDevice`. New-to-the-lab users usually inherit these from earlier sessions; if `insert_sessions` fails with "Probe type properties do not match" or similar, that is the cause — see `02_Insert_Data.ipynb` for the canonical pre-insert pattern.
- **`reinsert=`, not `skip_duplicates=`.** If you ever need to re-ingest, `sgi.insert_sessions("j1620210710.nwb", reinsert=True)` — destructive, cascades through every populate-tier output for this file. `insert_sessions` does **not** accept `skip_duplicates` and will raise `TypeError`.
- **Verify after ingestion** (uses the copy filename):
  ```python
  from spyglass.common import Session, Nwbfile, IntervalList, Raw
  Nwbfile  & {"nwb_file_name": nwb_copy_file_name}
  Session  & {"nwb_file_name": nwb_copy_file_name}
  IntervalList & {"nwb_file_name": nwb_copy_file_name}   # discover interval names for steps 2 and 3
  Raw      & {"nwb_file_name": nwb_copy_file_name}       # confirms a single Raw row + its sampling_rate
  ```

After this step, look at `IntervalList` and write down the names. Steps 2 and 3 each take **one** interval name, and they will likely not be the same one.

---

## (2) Trodes position pipeline for the `02_r1` interval

3-step shape, with `populate()` auto-merging into `PositionOutput`:

```python
from spyglass.position import PositionOutput
from spyglass.position.v1 import TrodesPosParams, TrodesPosSelection, TrodesPosV1

# 2a. Params — insert the canonical default once, site-wide. Reuse for all sessions.
TrodesPosParams().insert_default()   # creates the row named 'default'

# 2b. Selection — pick session + interval + params name.
key = {
    "nwb_file_name": nwb_copy_file_name,        # 'j1620210710_.nwb'
    "interval_list_name": "02_r1",
    "trodes_pos_params_name": "default",
}
TrodesPosSelection.insert1(key, skip_duplicates=True)

# 2c. Populate — runs the computation; make() also inserts into PositionOutput.
TrodesPosV1.populate(key)

# 2d. Fetch via the merge layer.
merge_key = PositionOutput.merge_get_part(key).fetch1("KEY")
position_df = (PositionOutput & merge_key).fetch1_dataframe()
# Columns: position_x, position_y, orientation, velocity_x, velocity_y, speed
```

Choice points:

- **`trodes_pos_params_name="default"` is the canonical default.** `TrodesPosParams().insert_default()` creates a row literally keyed `"default"`. Override only if you have non-default LED-tracking params (e.g. different smoothing window, max speed); register a new params row first with `TrodesPosParams.insert1({...}, skip_duplicates=True)` and pass that name in the selection.
- **`interval_list_name="02_r1"` is your choice.** I'm taking it from your prompt. Verify it actually exists in `IntervalList & {"nwb_file_name": nwb_copy_file_name}` first — if the NWB epochs / IntervalList rows landed under a different name (e.g. `"02_r1_valid_times"`, `"pos 1 valid times"`), `TrodesPosSelection.insert1` will raise an FK error.

---

## (3) LFP for the sleep epoch — TWO user-choice points

**Heads-up on the interval.** You said "LFP on the sleep epoch", but `02_r1` is a **run** epoch (the `r` is the convention for run; `s` is sleep). LFP and position can be (and usually are) computed on different intervals. So the `target_interval_list_name` you pass to `LFPSelection` is **not** `02_r1` — it's whichever sleep interval the NWB ingested. Inspect first:

```python
from spyglass.common import IntervalList
IntervalList & {"nwb_file_name": nwb_copy_file_name}
# Look for something like '01_s1' / '03_s2' / '<NN>_s<N>' — pick the one you mean by "the sleep epoch".
```

This is **choice point #1** — the skill cannot pick it for you.

**Choice point #2: which electrodes.** `LFPV1` does not implicitly take "all electrodes"; you tell it which subset to filter. The v1 surface for this is `LFPElectrodeGroup.create_lfp_electrode_group` (defined at `src/spyglass/lfp/lfp_electrode.py:29`) followed by `LFPSelection.insert1`. Common practice is to pick one representative electrode per tetrode/shank.

> Aside — if you find a tutorial calling `set_lfp_electrodes()`: that's the **v0** API on `common_ephys.LFPSelection`. The v1 LFP pipeline (which is what `LFPV1` is) has no such method. Use `create_lfp_electrode_group` + `LFPSelection.insert1` instead.

**Filter / sampling-rate gotcha.** `LFPV1.make()` looks up `FirFilterParameters` keyed on `(filter_name, filter_sampling_rate)`, **and the lookup uses the Raw recording's actual sampling rate** (`src/spyglass/lfp/v1/lfp.py:107-114`) — it's an exact equality match, not a Nyquist-style inequality. The shipped standard filter `"LFP 0-400 Hz"` is registered **only at 20000 Hz and 30000 Hz** (`src/spyglass/common/common_filter.py:577-595`). So:

- Don't make up a `filter_sampling_rate`. Derive it from `Raw`.
- For the typical SpikeGadgets recording the rate rounds to either 20000 or 30000, and the matching filter is already there.
- If your Raw rate is something else (rare), you'd have to register a new filter at that rate via `FirFilterParameters().add_filter(...)` first.

**`target_sampling_rate` has a schema default of 1000 Hz** (`src/spyglass/lfp/v1/lfp.py:40`). Leave it at the default unless you have a concrete reason to change it; a downstream `LFPBandV1` (theta / ripple / etc.) will key its `filter_sampling_rate` to this value, so 1000 Hz is the conventional path.

```python
import numpy as np
from spyglass.common import FirFilterParameters, Raw, IntervalList
from spyglass.lfp import LFPOutput, LFPElectrodeGroup
from spyglass.lfp.v1 import LFPSelection, LFPV1

# 3a. Make sure the shipped 'LFP 0-400 Hz' rows exist (idempotent).
FirFilterParameters().create_standard_filters()

# 3b. Pick the SLEEP interval — choice point #1. Replace 'NN_sN' below with
#     the actual sleep-interval name you confirmed against IntervalList.
sleep_interval_name = "NN_sN"   # e.g. "01_s1" — YOU MUST PICK

# 3c. Pick electrodes for LFP — choice point #2.
electrode_list = [0, 4, 8, 12]   # YOU MUST PICK; example shows one channel per tet
LFPElectrodeGroup.create_lfp_electrode_group(
    nwb_file_name=nwb_copy_file_name,
    group_name="lfp_main",          # any short label; reuse across sessions if you like
    electrode_list=electrode_list,
)

# 3d. Derive filter_sampling_rate from Raw (must match the standard-filter rate).
raw_sampling_rate = int(np.round(
    (Raw & {"nwb_file_name": nwb_copy_file_name}).fetch1("sampling_rate")
))
# raw_sampling_rate should be 20000 or 30000; if it isn't, you'd need to
# register a custom filter at that rate first.

# 3e. Selection + populate.
lfp_key = {
    "nwb_file_name": nwb_copy_file_name,
    "lfp_electrode_group_name": "lfp_main",
    "target_interval_list_name": sleep_interval_name,
    "filter_name": "LFP 0-400 Hz",
    "filter_sampling_rate": raw_sampling_rate,
    # target_sampling_rate omitted — schema default is 1000 Hz.
}
LFPSelection.insert1(lfp_key, skip_duplicates=True)
LFPV1.populate(lfp_key)

# 3f. Fetch via the merge layer.
lfp_merge_key = LFPOutput.merge_get_part(lfp_key).fetch1("KEY")
lfp_df = (LFPOutput & lfp_merge_key).fetch1_dataframe()
```

Choice points recap for step 3:

- **`target_interval_list_name`** — pick the sleep interval from `IntervalList` (not `02_r1`).
- **`electrode_list`** — pick which electrodes to filter.
- **`group_name`** — any label, but reuse it consistently if you'll do multiple LFP runs on the same channel set.
- `filter_name="LFP 0-400 Hz"` and `filter_sampling_rate=raw_sampling_rate` are the canonical defaults; do not invent a different `filter_sampling_rate`.
- `target_sampling_rate` — leave at the schema default of 1000 Hz.

---

## (4) Export everything for the paper

The export pipeline logs every Spyglass-table fetch you make during a "session", then captures the touched tables and analysis files into a reproducible bundle. Three phases — log, populate, package.

```python
from spyglass.common.common_usage import ExportSelection, Export

# 4a. Start logging. paper_id and analysis_id are YOUR labels — choice points.
sel = ExportSelection()
sel.start_export(paper_id="my_paper_2026", analysis_id="fig_lfp_v1")

# 4b. Run every fetch / restriction / join you want captured. For example:
#     - re-fetch position for figures
#     - re-fetch the LFP dataframe for figures
#     - any downstream analyses (band, ripple, decoding) you want bundled
position_df = (PositionOutput & merge_key).fetch1_dataframe()
lfp_df      = (LFPOutput & lfp_merge_key).fetch1_dataframe()
# ... whatever else the paper uses ...

sel.stop_export()

# 4c. Materialize the export.
Export().populate_paper(paper_id="my_paper_2026")

# 4d. Inspect what landed.
ExportSelection().preview_tables(paper_id="my_paper_2026")
ExportSelection().list_file_paths({"paper_id": "my_paper_2026"})
```

Choice points and gotchas:

- **`paper_id` and `analysis_id` are yours to pick.** Reusing `paper_id` on a later `populate_paper` **overwrites** the prior export with no prompt — bump `analysis_id` (or `paper_id`) for iterative exports.
- **Only one export can be active per Python process.** Calling `start_export` while another is open silently stops the first.
- **Compound `&` restrictions inside an export are logged as OR, not AND.** If you write `(Table & a) & b`, the export bundle gets every row matching `a` OR `b`. Use `Table & dj.AndList([a, b])` or a single SQL string if you need an AND intersection in the bundle.
- **Custom tables that don't inherit `SpyglassMixin` aren't logged on direct access.** If you have lab-private tables, either add `SpyglassMixin` or reach them through Spyglass tables that do.
- **For DANDI upload**, after `populate_paper` an admin runs `Export().prepare_files_for_export(paper_key)` — it patches the analysis NWBs (sex/species/age formatting, float16→float32, etc.) and updates the DataJoint external-table checksums. Non-admins cannot run this; coordinate with a lab admin if DANDI is the destination.

Canonical notebook for this whole step: `notebooks/05_Export.ipynb`.

---

## TL;DR — what you have to decide vs. what's already a default

| Step | Field | Default? | If not — what to pick |
|---|---|---|---|
| 1 | filename you pass | — | raw `j1620210710.nwb` (no underscore) |
| 2 | `trodes_pos_params_name` | yes — `"default"` (from `TrodesPosParams().insert_default()`) | a custom params row only if you need non-default LED tracking |
| 2 | `interval_list_name` | — | `"02_r1"` (verify it exists in `IntervalList`) |
| 3 | `target_interval_list_name` | — | the **sleep** interval from `IntervalList` (NOT `02_r1`) |
| 3 | `electrode_list` for `create_lfp_electrode_group` | — | which electrodes to filter; one-per-tet is common |
| 3 | `lfp_electrode_group_name` | — | any short label |
| 3 | `filter_name` | yes — `"LFP 0-400 Hz"` (`create_standard_filters()`) | only override if registering a custom filter |
| 3 | `filter_sampling_rate` | — | derive from `Raw.sampling_rate`; must be 20000 or 30000 to match a stock filter |
| 3 | `target_sampling_rate` | yes — schema default 1000 Hz | leave unset unless you have a specific reason |
| 4 | `paper_id`, `analysis_id` | — | your labels; don't reuse `paper_id` across iterations |

Run order: ingest (1) → verify intervals → params + selection + populate for Trodes (2) → standard filters + electrode group + selection + populate for LFP (3) → start export, re-fetch your figure inputs, stop export, populate_paper (4).
