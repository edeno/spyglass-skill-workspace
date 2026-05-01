# Custom table that pulls spikes across sort groups

Short answer: **don't put cross-sort-group membership in your own table's PK.** Spyglass already has a grouping table (`SortedSpikesGroup`) whose whole job is "name a set of curated units drawn from any number of sort groups so one downstream analysis can consume them as a unit." Your custom table should foreign-key `SortedSpikesGroup`, and then call `SortedSpikesGroup.fetch_spike_data(key)` inside `make()` to get the concatenated spikes across all the sort groups in that group.

Below is the recommended shape, the alternative if you really do need to author your own group, and the gotchas to avoid.

---

## Recommended: FK `SortedSpikesGroup`, fetch spikes in `make()`

`SortedSpikesGroup` (a `dj.Manual` master + `SortedSpikesGroup.Units` part, defined in `spyglass/spikesorting/analysis/v1/group.py`) holds:

- **Master PK**: `(nwb_file_name, unit_filter_params_name, sorted_spikes_group_name)`.
- **Part table `Units`**: one row per included sorted-unit set, FK'ing `SpikeSortingOutput.proj(spikesorting_merge_id='merge_id')`.

Each part row corresponds to one sort group's curated output (one merge_id from the `SpikeSortingOutput` merge table). A group with N tetrodes' worth of curated units therefore has N rows in `SortedSpikesGroup.Units`. `SortedSpikesGroup.fetch_spike_data(key)` walks the part rows and returns spike times for every unit across all of them.

That is exactly "spikes from all the tetrode sort groups." Your job is to (a) FK `SortedSpikesGroup` from your Computed table, and (b) call `fetch_spike_data` inside `make()`.

```python
import datajoint as dj

from spyglass.common import Session  # noqa: F401  (FK transitively via SortedSpikesGroup)
from spyglass.common.common_nwbfile import AnalysisNwbfile
from spyglass.spikesorting.analysis.v1.group import SortedSpikesGroup
from spyglass.utils import SpyglassMixin

schema = dj.schema("myuser_crossgroup_spikes")  # <database_user>_<suffix>


@schema
class MyAnalysisParams(SpyglassMixin, dj.Lookup):
    """Tunable knobs for the analysis."""

    definition = """
    my_params_name: varchar(32)
    ---
    my_params: blob
    """
    contents = [
        ["default", {"bin_s": 0.02}],
    ]


@schema
class MyAnalysisSelection(SpyglassMixin, dj.Manual):
    """Pair a SortedSpikesGroup with one parameter set."""

    definition = """
    -> SortedSpikesGroup
    -> MyAnalysisParams
    """


@schema
class MyAnalysis(SpyglassMixin, dj.Computed):
    """Analysis on spikes pooled across all sort groups in the SortedSpikesGroup."""

    definition = """
    -> MyAnalysisSelection
    ---
    -> AnalysisNwbfile
    result_object_id: varchar(40)
    """

    def make(self, key):
        params = (MyAnalysisParams & key).fetch1("my_params")

        # Spike times concatenated across every sort group in the group:
        # one entry in `spike_times` per included unit, regardless of which
        # sort group it came from.
        spike_times, unit_ids = SortedSpikesGroup().fetch_spike_data(
            key, return_unit_ids=True
        )

        # ... your computation on spike_times ...
        result_array = ...   # numpy array / DataFrame to store

        nwb_file_name = (SortedSpikesGroup & key).fetch1("nwb_file_name")
        with AnalysisNwbfile().build(nwb_file_name) as builder:
            obj_id = builder.add_nwb_object(result_array, table_name="result")
            analysis_file_name = builder.analysis_file_name

        self.insert1({
            **key,
            "analysis_file_name": analysis_file_name,
            "result_object_id": obj_id,
        })
```

Why this works for "spikes across sort groups":

- The Computed table is **session-scoped, not sort-group-scoped**. Its PK contains `nwb_file_name + sorted_spikes_group_name + unit_filter_params_name + my_params_name` — one row per analysis run, not per tetrode.
- Membership across sort groups lives in `SortedSpikesGroup.Units` (the part table), populated by you when you call `SortedSpikesGroup().create_group(...)` with the merge keys for whichever tetrodes you want to include.
- Inside `make()`, `fetch_spike_data` materializes the part rows. The part rows are not implicitly carried by the master FK — the helper method does the explicit join.

## Building (or refreshing) the group itself

Before you populate `MyAnalysis`, you populate `SortedSpikesGroup` with the union of all your tetrodes' curated unit sets:

```python
from spyglass.spikesorting.spikesorting_merge import SpikeSortingOutput
from spyglass.spikesorting.analysis.v1.group import (
    SortedSpikesGroup,
    UnitSelectionParams,
)

nwb_file = "myrat20240101_.nwb"

# On a fresh DB, populate the default UnitSelectionParams rows once.
UnitSelectionParams().insert_default()

# All curated unit sets (one per sort group / tetrode) for this session:
candidate_units = (
    SpikeSortingOutput.merge_restrict({"nwb_file_name": nwb_file})
    .proj(spikesorting_merge_id="merge_id")   # <-- the renamed key, not raw merge_id
    .fetch("KEY", as_dict=True)
)

SortedSpikesGroup().create_group(
    nwb_file_name=nwb_file,
    group_name="all_tetrodes",
    unit_filter_params_name="exclude_noise",
    keys=candidate_units,                     # one entry per sort group
)
```

Two things worth pinning down here:

1. **The part FKs `SpikeSortingOutput.proj(spikesorting_merge_id='merge_id')`** (`spyglass/spikesorting/analysis/v1/group.py:73`). Your `keys` entries must use the renamed field `spikesorting_merge_id`, not raw `merge_id` — `create_group` splats the dict straight into the part insert.
2. **`merge_restrict` (not `& {"nwb_file_name": ...}`)** on `SpikeSortingOutput`. The merge master has only `merge_id` as its heading, so a plain restriction silently returns the whole table. `merge_restrict` does the right thing.

## Alternative: author your own group

The pattern above (FK an existing group, call its helper in `make()`) is the recommended path because Spyglass already has it and downstream tools like `SortedSpikesDecodingV1` and `MuaEventsV1` use the same group. Roll your own only if `SortedSpikesGroup`'s shape genuinely doesn't fit (e.g., you need to group at tetrode granularity rather than per-unit).

If you do, the structural shape is a `dj.Manual` master plus a `dj.Part` whose rows FK the upstream entity (one part row per sort group included), with your Computed table FK'ing the master:

```python
@schema
class MySortGroupSet(SpyglassMixin, dj.Manual):
    definition = """
    -> Session
    my_set_name: varchar(32)
    """

    class Member(SpyglassMixinPart):
        # FK SpikeSortingOutput (with the same proj rename) so each member
        # row points at one sort group's curated output.
        definition = """
        -> master
        -> SpikeSortingOutput.proj(spikesorting_merge_id='merge_id')
        """
```

Inside that Computed table's `make()` you'd then iterate the part rows, fetch spikes per merge_id (e.g., via `SpikeSortingOutput().get_spike_times({"merge_id": ...})`), and concatenate yourself. This is strictly more code than `SortedSpikesGroup`, and any future downstream analysis you write will not benefit from the existing decoding/MUA tooling that already keys on `SortedSpikesGroup`. Skip unless you need it.

## Anti-patterns to avoid

- **Don't put a list of sort groups (or a list of merge_ids) directly in your Computed table's PK.** That blows up the dependency graph and makes per-row populates impossible. Group membership belongs in a Manual + Part pair upstream, not in your analysis row.
- **Don't FK `SpikeSortingOutput` from your Computed table directly.** That gives you one row per sort group, which is the opposite of what you want — you want one row that represents the *aggregate* across sort groups. FK the group instead.
- **Don't re-derive the unit set inside every `make()`** (e.g., "fetch all merge_ids for this nwb_file and run on them"). Two consumers of your pipeline would silently pick different unit sets if curation changes between calls. The grouping table is the artifact that pins membership.
- **Don't use `& {"nwb_file_name": f}` on `SpikeSortingOutput`** when discovering the merge_ids to feed into the group — the merge master's heading is only `merge_id`, so the unknown attr is silently dropped and the restriction returns the entire merge table. Use `SpikeSortingOutput.merge_restrict({...})` (or `merge_get_part`) instead.
- **Don't reuse a `sorted_spikes_group_name` across different `unit_filter_params_name` values for the same session.** Two such rows are distinct by PK, but `fetch_spike_data` only restricts the Units part by `(nwb_file_name, sorted_spikes_group_name)` (`spyglass/spikesorting/analysis/v1/group.py:171`) — it does not filter by `unit_filter_params_name`, so it would silently merge units across both filter settings.

## Where to verify

- `spyglass/spikesorting/analysis/v1/group.py` — `SortedSpikesGroup`, `SortedSpikesGroup.Units`, `create_group`, `fetch_spike_data`.
- `spyglass/spikesorting/spikesorting_merge.py` — `SpikeSortingOutput` merge master, `merge_restrict`, `get_spike_times`.
- `spyglass/common/common_nwbfile.py` — `AnalysisNwbfile().build(...)` context manager for storing your result.

If you want, share the kind of analysis you're going to run and I can fold in the actual computation (and any extra grouping you need on top, e.g. per-epoch IntervalList scoping).
