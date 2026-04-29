# Tetrodes per session for subject `aj80`

## Key idea — tetrode = electrode_group, not electrode

Each tetrode is one row in `ElectrodeGroup` (PK `nwb_file_name`, `electrode_group_name`), and each tetrode has **4** rows in `Electrode` (PK `nwb_file_name`, `electrode_group_name`, `electrode_id`). So if you count rows of `Electrode`, you get channels, not tetrodes — divide by 4 to recover tetrodes, but the cleaner answer is to count **distinct `electrode_group_name`** values per session.

Source-verified:

- `ElectrodeGroup` definition — `src/spyglass/common/common_ephys.py:31` (PK = `nwb_file_name`, `electrode_group_name`).
- `Electrode` definition — `src/spyglass/common/common_ephys.py:73` (inherits the ElectrodeGroup PK and adds `electrode_id`).
- `Session` carries `subject_id` as a (nullable) FK to `Subject` — `src/spyglass/common/common_session.py:19`.

## Canonical answer — `.aggr()`

```python
from spyglass.common import Session, Electrode

n_tetrodes = (Session & {"subject_id": "aj80"}).aggr(
    Electrode,
    n_tetrodes="count(distinct electrode_group_name)",
)

# One row per session, with the tetrode count
df = n_tetrodes.fetch(format="frame")
print(df)            # index = nwb_file_name, column = n_tetrodes
```

Why this works:

- `Session & {"subject_id": "aj80"}` selects every session whose `subject_id` is `aj80` (uses `Session`'s secondary `subject_id` FK to `Subject`).
- `.aggr(Electrode, n_tetrodes="count(distinct electrode_group_name)")` left-joins `Electrode` to each `Session` row on the shared key (`nwb_file_name`) and groups by the parent's PK, producing **one row per session**. The SQL `count(distinct electrode_group_name)` is what enforces "tetrodes, not electrodes" — it counts unique groups, not the 4-per-tetrode `Electrode` rows.

If a session has no `Electrode` rows yet (ingestion incomplete), the count for that session will be 0 — `.aggr` is a left-join.

## Equivalent shape (no `.aggr()` — pandas)

If you'd rather aggregate client-side:

```python
df = (
    (Session & {"subject_id": "aj80"}) * Electrode.proj("electrode_group_name")
).fetch(format="frame").reset_index()

per_session = (
    df[["nwb_file_name", "electrode_group_name"]]
    .drop_duplicates()
    .groupby("nwb_file_name")
    .size()
    .rename("n_tetrodes")
)
print(per_session)
```

The `drop_duplicates()` step on `(nwb_file_name, electrode_group_name)` is the equivalent of `count(distinct electrode_group_name)` — without it you'd be counting every `Electrode` row (≈ 4 per tetrode).

## Sanity check / verification

Before trusting the count, spot-check one session:

```python
nwb = (Session & {"subject_id": "aj80"}).fetch("nwb_file_name", limit=1)[0]

n_groups = len(set(
    (Electrode & {"nwb_file_name": nwb}).fetch("electrode_group_name")
))
n_electrode_rows = len(Electrode & {"nwb_file_name": nwb})

print(nwb, "tetrodes:", n_groups, "electrode rows:", n_electrode_rows)
# Expected for clean tetrode recording: n_electrode_rows == 4 * n_groups
```

If the ratio isn't 4:1, that session likely has non-tetrode probes (polymer, Neuropixels, …) — and "tetrode count" is no longer the right framing. In that case, restrict to ElectrodeGroup rows whose linked `Probe` / `ProbeType` actually identifies as a tetrode before counting.

## What I did not assume

- **I did not run a query against your DB** — I have no `$SPYGLASS_BASE_DIR` connection in this context, so the row counts above are *not* reported. Run the canonical `.aggr` snippet in your Python session to get the actual numbers for `aj80`.
- **`subject_id` is nullable on `Session`** (`common_session.py:26`). Sessions without a `subject_id` won't match the restriction — this is desired here (we're filtering to `aj80` exactly), but worth knowing if a count looks short.
- **Per-tetrode-per-electrode counts of 4** are a Frank-lab convention, not a schema-enforced invariant. The `count(distinct electrode_group_name)` form is correct regardless of group size; the 4× sanity check above is the place to confirm.
