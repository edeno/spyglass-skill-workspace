# Counting tetrodes per session for subject aj80

## What "tetrode" maps to in Spyglass

In Spyglass, electrodes are grouped into "electrode groups," and a tetrode is one such group (4 contacts sharing one `electrode_group_name`). So the question "how many tetrodes per session?" means: **for each session, how many distinct `electrode_group_name` values exist in `Electrode`?** Counting raw `Electrode` rows would over-count by a factor of 4.

Relevant tables:

- `Session` — keyed on `nwb_file_name`, has a (nullable) FK to `Subject` so `subject_id` is in its primary-key-adjacent attributes via the join.
- `ElectrodeGroup` — `(nwb_file_name, electrode_group_name)`; one row per tetrode/probe per session.
- `Electrode` — `(nwb_file_name, electrode_group_name, electrode_id)`; ~4 rows per tetrode.

For this question you can count rows in `ElectrodeGroup` directly (one row per tetrode) or count `distinct electrode_group_name` in `Electrode`. Both should give the same answer; counting from `ElectrodeGroup` is cheaper, but the prompt's framing ("how many tetrodes were recorded") is most safely answered by counting distinct `electrode_group_name` values from `Electrode`, which is robust if any electrode group ever fails to populate.

## Canonical answer with `.aggr()`

`.aggr()` is DataJoint's "group + aggregate" operator — left side is the group key, right side is what you aggregate over.

```python
import datajoint as dj
from spyglass.common import Session, Electrode

# One row per session (for subject aj80) with a tetrode count.
sessions_aj80 = Session & {"subject_id": "aj80"}

n_tetrodes_per_session = sessions_aj80.aggr(
    Electrode,
    n_tetrodes="count(distinct electrode_group_name)",
)

df = n_tetrodes_per_session.fetch(format="frame").reset_index()
print(df[["nwb_file_name", "n_tetrodes"]])
```

What this does:

1. `Session & {"subject_id": "aj80"}` restricts to sessions for subject `aj80`. (`subject_id` is a secondary attribute on `Session` — it's a nullable FK to `Subject`, so this restriction works directly.)
2. `.aggr(Electrode, ...)` groups by `Session`'s primary key (`nwb_file_name`) and joins to `Electrode`, then computes the named aggregation in SQL. `count(distinct electrode_group_name)` is the key piece — it deduplicates the 4 electrodes-per-tetrode.
3. `.fetch(format="frame")` returns a pandas DataFrame indexed by the group key.

## Equivalent without `.aggr()` (project + join + dedup in pandas)

If you'd rather not use `.aggr()` (or want to inspect the per-tetrode rows), you can join Session to Electrode, project just the columns you need, and deduplicate in pandas:

```python
import pandas as pd

q = (Session & {"subject_id": "aj80"}) * Electrode.proj("electrode_group_name")
df = q.fetch(format="frame").reset_index()

# Each (session, electrode_group_name) pair appears 4 times (once per electrode);
# drop_duplicates collapses to one row per tetrode.
tetrodes = df[["nwb_file_name", "electrode_group_name"]].drop_duplicates()

counts = (
    tetrodes.groupby("nwb_file_name")
    .size()
    .rename("n_tetrodes")
    .reset_index()
)
print(counts)
```

The `.proj("electrode_group_name")` keeps only what we need from `Electrode` and avoids pulling all the per-electrode geometry / impedance / filter columns across the wire. The final pandas `drop_duplicates` + `groupby.size()` matches what `count(distinct electrode_group_name)` does in SQL.

## A cheaper variant if you trust `ElectrodeGroup`

`ElectrodeGroup` already has one row per tetrode per session, so you can count it directly:

```python
n_groups = (Session & {"subject_id": "aj80"}).aggr(
    ElectrodeGroup,
    n_tetrodes="count(*)",
)
```

This is faster (no `distinct` over `Electrode`) but assumes `ElectrodeGroup` is fully populated — it should be, since `Electrode` has a FK to `ElectrodeGroup`, but counting from `Electrode` with `count(distinct ...)` is the more defensive form.

## Sanity checks before trusting the number

- Spot-check one session: `(Electrode & {"nwb_file_name": "<one_file>.nwb"}).fetch("electrode_group_name")` — count uniques manually and confirm it matches the row in `df`.
- Confirm 4 electrodes per group (tetrode): `len(...) / n_unique == 4`. If you see groups with 8, 16, 32, or 64 electrodes, those are silicon probes / shanks, not tetrodes — depending on what the lab calls a "tetrode" you may want to filter on `description` in `ElectrodeGroup` or on probe type before counting.
- Confirm `subject_id="aj80"` actually matched some sessions: `len(Session & {"subject_id": "aj80"})` should be > 0; if it's 0, check capitalization (`AJ80` vs `aj80`) and whether the subject is registered in `Subject`.

## Summary

```python
(Session & {"subject_id": "aj80"}).aggr(
    Electrode, n_tetrodes="count(distinct electrode_group_name)"
)
```

is the one-line answer. The "distinct" is load-bearing — without it you get 4× the number of tetrodes because `Electrode` has one row per contact, not per tetrode.
