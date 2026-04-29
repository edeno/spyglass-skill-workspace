# End-to-end flow for `j1620210710.nwb`

Welcome to Spyglass! Below is a four-phase walkthrough (ingest, position, LFP, export) using the v1 pipelines and reasonable defaults. I've flagged every place where you need to make a choice — those are marked `>> CHOOSE`.

A couple of upfront caveats so nothing surprises you:

- `02_r1` (the run epoch) is a **different interval** from the "sleep epoch" you mentioned for LFP. You'll need to pick the sleep interval name separately for step 3.
- The `filter_sampling_rate` you pass to LFP must **exactly match** the Raw data's sampling rate. The stock Spyglass filters are registered in `FirFilterParameters` only at `fs=20000` and `fs=30000`. It's a lookup, not a Nyquist check — if your raw fs is something else, you'd need to register a filter for it (uncommon, ask before doing this).

---

## Phase 1 — Ingest the NWB file

Drop `j1620210710.nwb` into your Spyglass raw-data directory (`$SPYGLASS_BASE_DIR/raw/`), then:

```python
import spyglass.common as sgc
from spyglass.data_import import insert_sessions

# Use the raw filename WITHOUT a trailing underscore.
# Spyglass copies the file to <name>_.nwb internally and ingests from that.
insert_sessions('j1620210710.nwb')
```

Sanity check what landed:

```python
nwb_file_name = 'j1620210710_.nwb'   # note: the trailing _ now applies for queries
sgc.Session & {'nwb_file_name': nwb_file_name}
sgc.IntervalList & {'nwb_file_name': nwb_file_name}
sgc.Raw & {'nwb_file_name': nwb_file_name}
sgc.Electrode & {'nwb_file_name': nwb_file_name}
```

Look at `IntervalList` — that's where you'll find both `02_r1` and your sleep interval name. Note the exact `interval_list_name` strings; you'll use them verbatim in phases 2 and 3.

>> CHOOSE: confirm the exact `interval_list_name` for the sleep epoch (e.g. `01_s1`, `03_s2`, etc.) by inspecting `IntervalList`.

---

## Phase 2 — Trodes position pipeline for `02_r1`

The v1 Trodes position pipeline lives in `spyglass.position.v1` and follows the standard `Params -> Selection -> Compute` triplet.

```python
from spyglass.position.v1 import (
    TrodesPosParams,
    TrodesPosSelection,
    TrodesPosV1,
)

# 1. Params: 'default' is the canonical pre-registered name.
#    Confirm it's there; insert_default() is idempotent if it isn't.
TrodesPosParams.insert_default()
TrodesPosParams()   # inspect — you should see a 'default' row

# 2. Selection: pick the (nwb_file, interval, params) tuple to compute on.
pos_key = {
    'nwb_file_name': nwb_file_name,
    'interval_list_name': '02_r1',          # the run epoch you named
    'trodes_pos_params_name': 'default',
}
TrodesPosSelection.insert1(pos_key, skip_duplicates=True)

# 3. Populate.
TrodesPosV1.populate(pos_key)

# 4. Verify.
TrodesPosV1 & pos_key
```

>> CHOOSE: if `default` params don't fit (e.g. unusual LED geometry, smoothing window), insert a custom `TrodesPosParams` row first and reference its name. For most use cases `default` is fine.

---

## Phase 3 — LFP on the sleep epoch

This phase has the most user-supplied choices. Two key things:

1. The user said "sleep epoch" — that is **NOT** `02_r1`. Pick the right interval from `IntervalList`.
2. You must pick which electrodes to compute LFP on. There's no implicit default — Spyglass v1 makes you commit to an electrode group.

The v1 LFP pipeline uses `LFPElectrodeGroup` for electrode selection (NOT the v0 `set_lfp_electrodes()` method on `common_ephys.LFPSelection` — that's the older surface and doesn't apply here).

```python
from spyglass.common import FirFilterParameters, IntervalList, Raw, Electrode
from spyglass.lfp.lfp_electrode import LFPElectrodeGroup
from spyglass.lfp.v1 import LFPSelection, LFPV1

# --- 3a. Pick the sleep interval ---
# Inspect to find the right name:
IntervalList & {'nwb_file_name': nwb_file_name}
sleep_interval = '01_s1'   # >> CHOOSE: replace with your actual sleep interval name

# --- 3b. Pick which electrodes ---
# Look at the electrode table to decide which electrode_ids to include:
Electrode & {'nwb_file_name': nwb_file_name}

electrode_list = [...]     # >> CHOOSE: list of electrode_id ints to LFP-process
group_name = 'sleep_lfp'   # >> CHOOSE: any label you want for this group

LFPElectrodeGroup.create_lfp_electrode_group(
    nwb_file_name=nwb_file_name,
    group_name=group_name,
    electrode_list=electrode_list,
)

# --- 3c. Pick the filter ---
# The standard wideband filter is 'LFP 0-400 Hz'.
# filter_sampling_rate must EQUAL the Raw fs (not just be > 800 Hz).
# Stock filters exist at fs=20000 and fs=30000 only.
raw_fs = (Raw & {'nwb_file_name': nwb_file_name}).fetch1('sampling_rate')
print(f'Raw sampling rate = {raw_fs} Hz')   # confirm 20000 or 30000

FirFilterParameters & {'filter_name': 'LFP 0-400 Hz',
                       'filter_sampling_rate': int(raw_fs)}
# ^ this row must exist. If it doesn't, raw_fs isn't 20000/30000 and you need
#   to register a filter for that fs before proceeding — pause and ask.

# --- 3d. Insert into LFPSelection ---
lfp_key = {
    'nwb_file_name': nwb_file_name,
    'lfp_electrode_group_name': group_name,
    'target_interval_list_name': sleep_interval,
    'filter_name': 'LFP 0-400 Hz',
    'filter_sampling_rate': int(raw_fs),
    # target_sampling_rate has a schema default of 1000 Hz —
    # leave it off unless you have a specific reason to change it.
}
LFPSelection.insert1(lfp_key, skip_duplicates=True)

# --- 3e. Populate ---
LFPV1.populate(lfp_key)

# --- 3f. Verify ---
LFPV1 & lfp_key
```

>> CHOOSE summary for phase 3:
- `sleep_interval` — the actual interval name (NOT `02_r1`).
- `electrode_list` — which electrode_ids contribute to LFP.
- `group_name` — a label for the electrode group.
- Confirm `filter_sampling_rate` matches Raw fs and the corresponding `FirFilterParameters` row exists.

---

## Phase 4 — Export for the paper

When you're ready to publish, Spyglass has an Export pipeline that captures every table the population steps touched, so a reviewer (or DANDI) can reconstruct what you did. The canonical entry point is the `05_Export` notebook (`notebooks/05_Export.ipynb` in the Spyglass repo).

The shape of an export looks like:

```python
from spyglass.common import LabMember
from spyglass.utils.dj_helper_fn import dj_replace
import datajoint as dj

# Most of the export logging is keyed by an export_name and a paper_id.
# You start an export, run your fetches/populates, then end & build the export.
# The exact API is in the Spyglass export module (see SharedTable / Export classes).
```

>> CHOOSE for phase 4:
- `paper_id` / export name — pick a stable label (e.g. paper short title or arXiv ID).
- Which downstream analyses to include in the export (position only? LFP only? both?). The export captures everything touched during the logged session, so plan a clean export run that touches exactly what you want shipped.
- Whether you're publishing to DANDI, FigURL/Kachery, or just a tarball — the `05_Export` notebook walks through each.

I'd recommend stepping through `05_Export.ipynb` interactively for your first paper export rather than scripting it blind — it has prompts for the choices above.

---

## TL;DR checklist of your choice points

| Phase | Choose |
|---|---|
| 1. Ingest | (none — `insert_sessions('j1620210710.nwb')` is enough) |
| 2. Position | confirm `02_r1` is the right interval; use `trodes_pos_params_name='default'` unless you need custom params |
| 3. LFP | the **sleep** `interval_list_name` (NOT `02_r1`); the `electrode_list`; a `group_name`; verify `filter_sampling_rate == raw fs` and that filter exists in `FirFilterParameters` |
| 4. Export | export/paper id; what to include; publication target (DANDI / FigURL / local) |

Run each phase, verify the table populated (`& key` returns a row), then move on. If a `populate` raises, the most common culprits are missing `FirFilterParameters` for your fs (phase 3) or a typo in `interval_list_name` (phases 2 and 3) — both fail fast.
