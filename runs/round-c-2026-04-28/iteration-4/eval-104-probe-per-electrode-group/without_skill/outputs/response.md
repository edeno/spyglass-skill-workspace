# Probe model per electrode group for `j1620210710_.nwb`

In Spyglass, the relationship between electrode groups and probe models is captured by the `Electrode` table (and adjacent tables in `spyglass.common.common_ephys` / `common_device`). Each row in `Electrode` carries both `electrode_group_name` and `probe_id` (FK to `Probe`), and `Probe` carries `probe_type` / `probe_model` (depending on Spyglass version — older schemas store `probe_type`, newer ones add `probe_id`/`probe_model` distinction). To get one probe model per electrode group, group by `electrode_group_name`.

## Query

```python
import datajoint as dj
from spyglass.common import Nwbfile, Electrode, ElectrodeGroup
from spyglass.common.common_device import Probe

nwb_file_name = "j1620210710_.nwb"

# Join ElectrodeGroup -> Electrode -> Probe, restrict to this session,
# and pull distinct (electrode_group_name, probe model) pairs.
query = (
    (ElectrodeGroup & {"nwb_file_name": nwb_file_name})
    * Electrode
    * Probe
)

# Distinct group/probe combinations
result = dj.U("electrode_group_name", "probe_id").aggr(
    query, n_electrodes="count(*)"
).fetch(as_dict=True)

for row in result:
    print(row)
```

Equivalently with pandas for a clean view:

```python
df = (
    (Electrode & {"nwb_file_name": nwb_file_name}) * Probe
).fetch(format="frame").reset_index()

df.groupby("electrode_group_name")[["probe_id"]].agg(
    lambda s: sorted(set(s))
)
```

## Notes / caveats

- The exact probe column name depends on Spyglass version. Run `Probe.heading` to confirm — recent Spyglass uses `probe_id` as primary key with descriptive fields like `probe_type`, `probe_description`, `num_shanks`. Older code paths used `probe_type` directly on `Electrode`.
- `ElectrodeGroup` itself stores `target_hemisphere`, `description`, `region_id` — not the probe. The probe link lives on `Electrode` (per-channel), so you must aggregate up. In well-formed NWB ingests, all electrodes in a group share one probe, but the aggregation makes that visible (and surfaces any inconsistency as multiple probe ids per group).
- If `j1620210710_.nwb` isn't ingested yet, this returns empty — verify with `Nwbfile & {"nwb_file_name": "j1620210710_.nwb"}` first.
- Without DB access I can't tell you the actual probe models for this specific session. For Frank-lab `j16` recordings circa 2021-07-10 these are typically 32-channel polymer probes or tetrode arrays, but that's a guess from the filename convention — confirm by running the query.

I cannot run this against your database from here, so the per-group probe identities for `j1620210710_.nwb` are unknown to me; the query above is what produces the answer.
