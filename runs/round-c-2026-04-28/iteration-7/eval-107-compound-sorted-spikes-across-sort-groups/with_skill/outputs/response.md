# Custom table over "all tetrode sort groups" without listing `sort_group_id` by hand

## TL;DR

Don't FK `SortGroup` (or `SpikeSortingOutput`) directly with one row per
tetrode — that's the shape that forces you to enumerate `sort_group_id`
values. Instead, use Spyglass's existing **group table** pattern:

1. Discover the curated merge keys for the session programmatically.
2. Bundle them into a single `SortedSpikesGroup` row via
   `create_group(..., keys=<all the merge keys>)`.
3. Have your custom table FK `SortedSpikesGroup` (one row =
   one `(nwb_file_name, sorted_spikes_group_name, unit_filter_params_name)`).
4. In `make()`, call `SortedSpikesGroup().fetch_spike_data(key, ...)` to
   get back spike times across every tetrode.

That replaces the "list every sort_group_id" pattern with a single
group-name FK. This is the shape `SortedSpikesDecodingV1` and
`MuaEventsV1` already use.

## Why a group table

A group table is a `dj.Manual` master + `dj.Part` member table whose job
is precisely "assign a user-named subset of upstream rows a single name
so downstream pipelines FK the *group* instead of N upstream rows"
(see `references/group_tables.md`). `SortedSpikesGroup`
(`spyglass/spikesorting/analysis/v1/group.py`) is the prebuilt one for
sorted units — its part table `SortedSpikesGroup.Units` FKs
`SpikeSortingOutput.proj(spikesorting_merge_id='merge_id')`, so each
member row is one curated sort. You can put 1, N, or all-tetrodes-worth
of merge keys in there; downstream tables FK the master row, which
carries one name, regardless of cardinality.

This is a different pattern from a merge table — merges aggregate
*versions* of the same analysis under one `merge_id`; groups aggregate
*many distinct upstream entities* under one user-named key. You want a
group here.

## Step 1 — discover the merge keys for *all* this session's sortings

Assuming you've already run the v1 pipeline through to publication into
`SpikeSortingOutput.CurationV1` for every tetrode (i.e. `SortGroup` →
recording → artifact → sort → curation → `SpikeSortingOutput.insert(...)`
for each `sort_group_id`), the merge layer can enumerate them in one
call. Project the renamed key — `SortedSpikesGroup.Units` requires
`spikesorting_merge_id`, NOT raw `merge_id`:

```python
from spyglass.spikesorting.spikesorting_merge import SpikeSortingOutput

nwb_file = "your_session_.nwb"

candidate_units = (
    SpikeSortingOutput.merge_restrict({"nwb_file_name": nwb_file})
    .proj(spikesorting_merge_id="merge_id")
    .fetch("KEY", as_dict=True)
)
print(len(candidate_units), "curated sortings for this session")
```

Two cardinality notes worth checking before you commit:

- `SpikeSortingOutput` is a merge master — its only PK field is
  `merge_id`. Naive `& {"nwb_file_name": ...}` silently returns the
  whole table. **Always use `merge_restrict` here**, not `&`. (Common
  Mistake #6 in `SKILL.md`.)
- One sortgroup can produce more than one curated row over time (re-runs,
  different params). If you only want one curation per tetrode, narrow
  with the part-table fields you care about, e.g. add
  `interval_list_name`, the curation description, or restrict to the
  most recent `time_of_sort`. Inspect first:

```python
print((SpikeSortingOutput.CurationV1 & {"nwb_file_name": nwb_file})
      .fetch("KEY", "sort_group_id", "curation_id", as_dict=True))
```

## Step 2 — create one `SortedSpikesGroup` covering every tetrode

```python
from spyglass.spikesorting.analysis.v1.group import (
    SortedSpikesGroup,
    UnitSelectionParams,
)

group_name = "all_tetrodes"
filter_name = "exclude_noise"   # or "all_units" / "default_exclusion"

# Inspect-before-write — create_group raises if this triple already exists.
existing = SortedSpikesGroup & {
    "nwb_file_name": nwb_file,
    "sorted_spikes_group_name": group_name,
    "unit_filter_params_name": filter_name,
}
print(len(existing), "existing rows for this group key")

SortedSpikesGroup().create_group(
    nwb_file_name=nwb_file,
    group_name=group_name,
    unit_filter_params_name=filter_name,
    keys=candidate_units,           # the list of {"spikesorting_merge_id": ...}
)

print(len(SortedSpikesGroup.Units & {
    "nwb_file_name": nwb_file,
    "sorted_spikes_group_name": group_name,
}), "units bundled into the group")
```

Two gotchas:

- `keys` entries must use `spikesorting_merge_id`, not `merge_id`. The
  part table FKs the *renamed* projection
  (`spikesorting/analysis/v1/group.py:73`) and `create_group` splats
  each dict straight into the part insert (`group.py:97-103`).
- `SortedSpikesGroup.fetch_spike_data` only restricts `Units` by
  `(nwb_file_name, sorted_spikes_group_name)` — it does NOT filter by
  `unit_filter_params_name`. If you ever create two rows with the same
  `sorted_spikes_group_name` under different filter params,
  `fetch_spike_data` silently merges their units. Keep
  `sorted_spikes_group_name` unique per session unless you've verified
  this matches your intent.

## Step 3 — your custom table FKs the group, not the sort groups

Now the actual point: your custom analysis table takes one FK to
`SortedSpikesGroup`. No `sort_group_id` enumeration anywhere in your
schema.

```python
import datajoint as dj

from spyglass.common import Session, IntervalList   # noqa: F401
from spyglass.common.common_nwbfile import AnalysisNwbfile
from spyglass.spikesorting.analysis.v1.group import SortedSpikesGroup
from spyglass.utils import SpyglassMixin, SpyglassMixinPart

# Personal schema MUST be <database.user>_<suffix>; replace `myuser`
# with whatever `dj.config["database.user"]` returns for you. Do NOT
# prefix with `spyglass_` — that hits a MySQL permission error.
schema = dj.schema("myuser_tetrodepop")


@schema
class TetrodePopParams(SpyglassMixin, dj.Lookup):
    definition = """
    tetrodepop_params_name: varchar(32)
    ---
    tetrodepop_params: blob
    """
    contents = [
        ["default", {"bin_s": 0.020, "smoothing_sigma": 0.015}],
    ]


@schema
class TetrodePopSelection(SpyglassMixin, dj.Manual):
    definition = """
    -> SortedSpikesGroup
    -> IntervalList
    -> TetrodePopParams
    """


@schema
class TetrodePop(SpyglassMixin, dj.Computed):
    definition = """
    -> TetrodePopSelection
    ---
    -> AnalysisNwbfile
    population_object_id: varchar(40)
    """

    def make(self, key):
        params = (TetrodePopParams & key).fetch1("tetrodepop_params")
        nwb_file_name = (Session & key).fetch1("nwb_file_name")

        # The "no-enumerate sort_group_id" payoff: one call returns
        # spike times across every tetrode in the group.
        spike_times, unit_ids = SortedSpikesGroup().fetch_spike_data(
            key, return_unit_ids=True,
        )

        # ... your analysis here, e.g. binned firing rates / population vector ...
        result = compute_population_vector(spike_times, params)  # placeholder

        with AnalysisNwbfile().build(nwb_file_name) as builder:
            obj_id = builder.add_nwb_object(result, table_name="population")
            analysis_file_name = builder.analysis_file_name

        self.insert1({
            **key,
            "analysis_file_name": analysis_file_name,
            "population_object_id": obj_id,
        })
```

That's the entire pattern. The selection row is one tuple
`(nwb_file_name, sorted_spikes_group_name, unit_filter_params_name,
interval_list_name, tetrodepop_params_name)`; everything to do with
"there happen to be 12 tetrodes in this session" is hidden inside the
group's part table and `fetch_spike_data`.

## Why not bypass the group table and FK something else?

Three options I considered and rejected:

- **FK `SortGroup` directly with `(nwb_file_name, sort_group_id)` PK.**
  Forces one row per tetrode in your selection — exactly the
  enumeration you want to avoid.
- **FK `SpikeSortingOutput` directly.** Same problem — one row per
  curated sortgroup. Plus you'd need to roll your own "fetch spike
  times across N merge_ids" loop, duplicating
  `SortedSpikesGroup.fetch_spike_data`.
- **Add a custom `MyTetrodeSet` `dj.Manual` whose part table FKs
  `SortGroup`.** Workable, but it reinvents `SortedSpikesGroup` without
  the unit-label filtering (`UnitSelectionParams`), the
  `fetch_spike_data` / `get_spike_indicator` / `get_firing_rate`
  helpers, or compatibility with `SortedSpikesDecodingV1` /
  `MuaEventsV1` if you ever want to reuse the same set downstream. Use
  this only if you genuinely need to operate on *recordings/electrodes*
  rather than spike times — in which case
  `references/custom_pipeline_authoring.md § Building from Ingested
  Tables` shows the equivalent shape over `ElectrodeGroup`.

## Checklist before you commit

- `dj.config["database.user"]` matches your schema prefix
  (`myuser_tetrodepop` in the sketch above).
- `SpikeSortingOutput.merge_restrict({"nwb_file_name": nwb_file})`
  returns the count of curated sortings you expect for the session.
- Each candidate-unit dict has key `spikesorting_merge_id`, not
  `merge_id`.
- `(SortedSpikesGroup & group_key)` returns 1 row, and
  `len(SortedSpikesGroup.Units & group_key)` is the number of tetrodes
  you intended.
- `SpyglassMixin` is the **first** base class on every table you
  declare (the inheritance order is enforced; getting it wrong silently
  breaks method overrides).

## Sources used

- `references/group_tables.md` — group-table shape, `create_group`
  worked example, `spikesorting_merge_id` rename, group-vs-merge
  comparison.
- `references/spikesorting_v1_analysis.md` — `SortedSpikesGroup` PK,
  `fetch_spike_data` semantics, `UnitSelectionParams` defaults.
- `references/spikesorting_v1_pipeline.md` — `SortGroup`,
  `SpikeSortingOutput` merge layer, v1 publication path.
- `references/custom_pipeline_authoring.md` — Params / Selection /
  Computed five-step decision tree, schema-name / `database.user`
  rule, `AnalysisNwbfile().build()` pattern, `SpyglassMixin`-first MRO
  rule.
- `references/merge_methods.md` (via Common Mistake #6 in `SKILL.md`)
  — why `SpikeSortingOutput & {"nwb_file_name": ...}` is unsafe.
