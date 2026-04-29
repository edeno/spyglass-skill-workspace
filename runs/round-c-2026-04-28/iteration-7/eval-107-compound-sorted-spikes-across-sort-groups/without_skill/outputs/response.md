# Aggregating spikes across all tetrode sort groups in a custom table

The trick is: **don't put `sort_group_id` in your table's primary key as something the user types.** Instead, make your table's primary key whatever scope you want one row to represent (e.g., one row per `nwb_file_name` + `sort_interval_name` + your analysis params), and resolve "all the tetrodes" by **querying** the upstream tables in `make()`.

Below is the pattern, then a concrete sketch.

## Pattern

1. **Define the grain of *your* table** — what does one row mean? Probably one row per session (or per session × sort interval × your params), not one row per sort group. That choice is what frees you from hand-listing IDs.
2. **In `make(self, key)`, restrict the upstream curated-spikes table by `key`** to get every sort group that matches. Spyglass's spike-sorting v0 pipeline stores curated spikes in `sgs.CuratedSpikeSorting` (v0) or `sgss.CurationV1` / `sgss.SpikeSortingOutput` (v1), each row keyed by `sort_group_id` among other things. Any query restricted by your higher-level key will return *all* sort groups that satisfy it — that's exactly the "don't enumerate by hand" behavior you want.
3. **Filter to tetrode sort groups** by joining against `sgs.SortGroup.SortGroupElectrode * common.Electrode` and filtering on `electrode_group_name` / `probe_type` (or whatever marks your tetrodes). The validity of the filter depends on how your lab labels tetrodes — `probe_type LIKE "tetrode%"` is common, but check with `(sgs.SortGroup.SortGroupElectrode * Electrode & key).fetch(...)` first.
4. **Iterate the resulting keys, fetch each unit's spike times, concatenate / aggregate, and `self.insert1`** with an AnalysisNwbfile if you're storing arrays.

This is the same shape as `PositionInfo`-style "session-level summary" tables in Spyglass: the table itself is keyed at the session level, and `make()` walks the per-channel / per-group children.

## Concrete sketch (spike sorting v0)

```python
import datajoint as dj
import numpy as np
import spyglass.common as sgc
import spyglass.spikesorting.v0 as sgs
from spyglass.utils.dj_mixin import SpyglassMixin

schema = dj.schema("my_user_compound_spikes")

@schema
class CompoundTetrodeSpikesParams(SpyglassMixin, dj.Manual):
    definition = """
    compound_params_name : varchar(64)
    ---
    probe_type_match : varchar(64)   # e.g. 'tetrode_12.5' or '%tetrode%'
    """

@schema
class CompoundTetrodeSpikesSelection(SpyglassMixin, dj.Manual):
    definition = """
    -> sgc.Nwbfile
    -> sgs.SortInterval                 # whatever scopes "this session's sort"
    -> CompoundTetrodeSpikesParams
    """

@schema
class CompoundTetrodeSpikes(SpyglassMixin, dj.Computed):
    definition = """
    -> CompoundTetrodeSpikesSelection
    ---
    n_units : int
    n_sort_groups : int
    -> sgc.AnalysisNwbfile               # if you store the spike arrays
    object_id : varchar(40)
    """

    def make(self, key):
        probe_match = (CompoundTetrodeSpikesParams & key).fetch1("probe_type_match")

        # 1. Find every sort_group_id for this session whose electrodes are tetrodes.
        sg_elec = sgs.SortGroup.SortGroupElectrode * sgc.Electrode
        tetrode_groups = (
            sg_elec
            & {"nwb_file_name": key["nwb_file_name"]}
            & f'probe_type LIKE "{probe_match}"'
        ).fetch("sort_group_id", as_dict=False)
        tetrode_groups = np.unique(tetrode_groups).tolist()

        # 2. Restrict CuratedSpikeSorting by *the session-level key plus those groups*.
        #    No hand-listing: the IN-clause is built from the query above.
        curated = (
            sgs.CuratedSpikeSorting
            & {"nwb_file_name": key["nwb_file_name"],
               "sort_interval_name": key["sort_interval_name"]}
            & [{"sort_group_id": sg} for sg in tetrode_groups]
        )

        # 3. Walk every matching row and pull units.
        all_spike_times = []
        for sub_key in curated.fetch("KEY"):
            units = (sgs.CuratedSpikeSorting.Unit & sub_key).fetch(
                "spike_times", as_dict=False
            )
            all_spike_times.extend(units)

        # 4. Persist.  (AnalysisNwbfile usage elided; standard Spyglass pattern.)
        analysis_file = sgc.AnalysisNwbfile().create(key["nwb_file_name"])
        # ... write all_spike_times into analysis_file, get object_id ...
        sgc.AnalysisNwbfile().add(key["nwb_file_name"], analysis_file)

        self.insert1({
            **key,
            "n_units": sum(len(s) for s in all_spike_times),
            "n_sort_groups": len(tetrode_groups),
            "analysis_file_name": analysis_file,
            "object_id": "<from nwb write>",
        })
```

## Things worth verifying for your data

- **v0 vs v1 spike sorting.** If your lab is on v1 (`spyglass.spikesorting.v1`), swap `sgs.CuratedSpikeSorting` for `SpikeSortingOutput` (the merge table) and use `SpikeSortingOutput.get_spike_times(...)` / its merge-id resolver instead of `.Unit`. The "restrict-by-session-key, fetch all matching sort groups" idea is identical; only the upstream table names change.
- **How tetrodes are labeled in your DB.** Run something like `(sgs.SortGroup.SortGroupElectrode * sgc.Electrode & {"nwb_file_name": ...}).fetch("probe_type", "electrode_group_name")` once and confirm the filter string. Some labs encode tetrode-ness in `electrode_group_name` (e.g., `tet_03`) rather than `probe_type`.
- **Curation selection.** `CuratedSpikeSorting` may have multiple curations per sort group. If so, add a curation-id parameter to your params table or pick `curation_id = max(...)` deterministically — don't silently grab all curations or you'll double-count units.
- **Unit quality filter.** If you only want "good" units, restrict `.Unit` by `label` (e.g., `& 'label="" OR label LIKE "%accept%"'`). Decide this explicitly; the default is "every unit row, including noise."

## The key idea

You're not avoiding `sort_group_id` — you're letting **DataJoint's restriction algebra enumerate it for you**. Your table's primary key sits *above* sort group; `make()` does `(UpstreamTable & key)` and inherits every sort group that matches. That's the idiomatic DataJoint way to express "do this for all children of this parent."
