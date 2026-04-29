Yes — Spyglass has a first-class abstraction for exactly this. It's called **`SortedSpikesGroup`** and it lives in `spyglass.spikesorting.analysis.v1.group`. The whole point of it is to bundle multiple sorted-spikes outputs (e.g. one per tetrode / sort group) under a single named handle so downstream code never has to re-do the join.

## The short version

1. Curate your sorts as usual (v1 pipeline → `CurationV1`).
2. Pick which curations belong together (all your CA1 tetrodes, say) and insert them as one group via `SortedSpikesGroup.create_group(...)`.
3. From then on, fetch all units across that group with a single call: `SortedSpikesGroup.fetch_spike_data(group_key)`.

You define the grouping once. The "manual join across tetrode sort groups" disappears.

## Concrete usage

```python
from spyglass.spikesorting.analysis.v1.group import SortedSpikesGroup
from spyglass.spikesorting.v1 import CurationV1

nwb_file_name = "mysession_.nwb"

# 1. Find the curated sorts you want to bundle.
#    Typically you filter CurationV1 down to the curation_id you trust
#    for each sort group / tetrode in the target region.
keys = (CurationV1 & {
    "nwb_file_name": nwb_file_name,
    "curation_id": 1,          # whatever your "final" curation id is
    # ... plus whatever selects your hippocampal tetrodes,
    # e.g. a restriction joined against an electrode-region table
}).fetch("KEY")

# 2. Register the group. This is a one-time insert per (session, group_name).
SortedSpikesGroup.create_group(
    nwb_file_name=nwb_file_name,
    group_name="hippocampus",
    keys=keys,
)

# 3. Later, anywhere in your analysis code:
group_key = {
    "nwb_file_name": nwb_file_name,
    "sorted_spikes_group_name": "hippocampus",
}

spike_times = SortedSpikesGroup.fetch_spike_data(group_key)
# -> list of 1-D np.ndarrays, one per unit, already pooled across tetrodes
```

`fetch_spike_data` accepts a `time_slice=(t0, t1)` kwarg if you only want spikes inside an interval, and a `return_unit_ids=True` kwarg if you need the (merge_id, unit_id) provenance for each returned array.

There's also a sibling `UnitSelectionParams` / `SortedSpikesGroup.Units` part-table that records which `(merge_id, unit_id)` pairs are in the group, so the membership is queryable in DataJoint, not just an in-memory list.

## Why this is the right abstraction

- **It's the input format the decoder expects.** `spyglass.decoding.v1.sorted_spikes.SortedSpikesDecodingSelection` keys directly off `SortedSpikesGroup`. So if your reason for pooling hippocampal units is "I want to decode position from CA1," you were going to need this object anyway.
- **It's merge-table aware.** Under the hood the group references `SpikeSortingOutput` (the merge table that unifies v0 / v1 / imported sorts), so a group can mix sources if you ever need to.
- **The join is recorded in the database.** Anyone re-running your analysis gets the same set of units, by name, without re-deriving the tetrode list.

## Things to check / caveats

- **Region tagging is on you.** Spyglass doesn't infer "this tetrode is in CA1" — you decide which `CurationV1` keys go into the `"hippocampus"` group. If you have `BrainRegion` / electrode-location info populated, restrict on that when building `keys`; otherwise restrict by `sort_group_id` list.
- **One curation per unit.** You typically want exactly one curation_id per sort group in the bundle; otherwise you'll get duplicate units. Filter `CurationV1` accordingly before passing to `create_group`.
- **v1 pipeline.** `SortedSpikesGroup` lives under `spikesorting.analysis.v1`. If your sorts are still in the v0 pipeline, insert them into `SpikeSortingOutput` (the merge table) first; v0 keys can participate via the merge table.
- **Naming.** `group_name` is a primary key alongside `nwb_file_name`, so use a stable convention (`"hippocampus"`, `"ca1"`, `"mec_layer2"`, …); renaming later means re-inserting.

## What I'm less sure about (verify in your installed version)

- Exact attribute name for the group identifier in the primary key: I've seen both `sorted_spikes_group_name` and just `group_name` referenced in different versions of the codebase. Check with `SortedSpikesGroup.heading` after import — it'll show the real PK.
- Whether your installation exposes `fetch_spike_data` as a classmethod or instance method — both forms exist across versions; `(SortedSpikesGroup & group_key).fetch_spike_data()` works in either case.

If you tell me which Spyglass version you're on (`spyglass.__version__`) I can pin the exact signatures, but the pattern above — `create_group` once, `fetch_spike_data` thereafter — is stable across recent releases.
