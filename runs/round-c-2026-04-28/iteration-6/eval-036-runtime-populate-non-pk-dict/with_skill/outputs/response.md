# `populate(key)` is silently iterating the whole `SpikeSortingSelection`, not filtering by your `sorter`

Spyglass is not ignoring your kwarg — DataJoint is. Your `populate({...})` call ran every unprocessed row in `SpikeSortingSelection`, and one of those rows happens to have `sorter='kilosort2'`. The traceback is from the spikeinterface dispatch when populate hit *that* row, not yours.

This is failure signature **G** in `runtime_debugging.md`: *"`populate(key)` with a non-PK dict iterates the whole Selection."*

## Symptom

```
SpikeSorting.populate({'nwb_file_name': 'j1620210710_.nwb',
                       'sorter': 'mountainsort4'})
# ...later...
# Exception: The sorter kilosort2 is not installed
```

## Most likely root cause

The dict you passed contains zero fields from `SpikeSortingSelection`'s **primary key**, so DataJoint silently discards every entry in it and the restriction degenerates to a no-op. `populate()` then iterates the entire un-populated Selection and dies on the first row that names a sorter (or other parameters) you don't have installed.

Unlike `fetch1()`, which raises `DataJointError` on a too-loose dict, `populate()` raises **nothing** for this case.

## Why that explanation fits (mechanism — `key_source` is the load-bearing concept)

`SpikeSortingSelection`'s definition (`spyglass/spikesorting/v1/sorting.py:199-207`) is:

```python
class SpikeSortingSelection(SpyglassMixin, dj.Manual):
    definition = """
    sorting_id: uuid                 # <-- THE ONLY primary-key field
    ---
    -> SpikeSortingRecording         # secondary attrs (incl. nwb_file_name)
    -> SpikeSorterParameters         # secondary attrs (incl. sorter)
    -> IntervalList
    """
```

The PK is just `sorting_id`. `nwb_file_name` and `sorter` live in **secondary** attributes (inherited via the FKs to `SpikeSortingRecording` and `SpikeSorterParameters`).

Now the chain of three behaviors that combine into the silent failure:

1. **DataJoint default for `dj.Computed.key_source`** is `parent.proj()` — i.e., the parent table projected to **PK only**. (`autopopulate.py`, `key_source` property: `else table.proj()`.) `SpikeSorting`'s `key_source` is therefore `SpikeSortingSelection.proj()`, whose heading is just `{sorting_id}`. Nothing else.
2. **`populate(restrictions)` restricts against `key_source`**, not against the full Selection.
3. **DataJoint's `&` silently drops dict keys that aren't in the heading.** Since neither `nwb_file_name` nor `sorter` is in `key_source.heading`, both are discarded. The restriction becomes the empty restriction → matches every unprocessed row.

So `populate()` walks every row in the Selection, including ones inserted by other users / older runs / different sorters, and one of those tries to dispatch `kilosort2`.

## Fastest confirmation checks

```python
from spyglass.spikesorting.v1 import SpikeSorting, SpikeSortingSelection

# 1. Show key_source's heading is PK-only:
print(SpikeSorting.key_source.heading.names)            # ('sorting_id',)

# 2. Show the dict-restriction is a no-op against key_source:
loose = {'nwb_file_name': 'j1620210710_.nwb', 'sorter': 'mountainsort4'}
print(len(SpikeSorting.key_source))                     # N
print(len(SpikeSorting.key_source & loose))             # also N — discarded!

# 3. But against the full Selection, the same dict DOES filter:
print(len(SpikeSortingSelection & loose))               # the rows you actually want
```

If (1) and (2) come out as described, the diagnosis is confirmed.

## Minimal fix — restrict the Selection first, then pass a PK-only key to `populate`

```python
from spyglass.spikesorting.v1 import SpikeSorting, SpikeSortingSelection

key = {'nwb_file_name': 'j1620210710_.nwb', 'sorter': 'mountainsort4'}

# Single row:
sort_key = (SpikeSortingSelection & key).fetch1('KEY')   # validates uniqueness
SpikeSorting.populate(sort_key)

# Multi-row (e.g., several sorting_ids that all share these secondary attrs):
SpikeSorting.populate((SpikeSortingSelection & key).proj())
```

`fetch1('KEY')` returns just the PK fields (`{sorting_id: <uuid>}`), which `populate` *can* match against `key_source`. `.proj()` reduces a multi-row restriction to PK only with the same effect.

Note: if `(SpikeSortingSelection & key).fetch1('KEY')` raises `DataJointError: ... should only be called on relations with exactly one tuple`, that's the **good** failure mode — it means more than one `sorting_id` matches your filter (e.g., two interval lists for the same nwb+sorter), and you need to add another field. That's exactly what `populate(loose_dict)` was hiding from you.

## Robust fix / generalization

This is the `dj.Computed` default — it is **not Spyglass-specific** and applies to every `*V1.populate(...)` entry point in Spyglass:

- `SpikeSortingRecording.populate(...)` → fix `SpikeSortingRecordingSelection` first (its PK is `recording_id`)
- `ArtifactDetection.populate(...)` → fix `ArtifactDetectionSelection`
- `MetricCuration.populate(...)`, `FigURLCuration.populate(...)`, `CurationV1.populate(...)`, etc.
- Any LFP, position, decoding `*V1` table where the Selection's PK is a uuid / synthetic key

The general pattern:

```python
# For ANY ComputedV1 entry point:
sel_key = (TheTablesSelection & friendly_dict).fetch1('KEY')   # or .proj() for many
TheTable.populate(sel_key)
```

If you're authoring your own pipeline and want to keep `populate({'sorter': ...})` working directly, override `key_source` on your Computed class to expose the secondary attrs:

```python
@property
def key_source(self):
    return SpikeSortingSelection   # not .proj() — keep the full heading
```

(That has tradeoffs — see `custom_pipeline_authoring.md` — but it's the lever if you want the restriction to bite.)

## Watch-outs

- **`fetch1()` raises, `populate()` doesn't.** This asymmetry is the entire footgun. If you ever build muscle memory from `fetch1` exploding on loose keys, do not transfer it to `populate`.
- **One Selection table per `populate` target.** For `SpikeSorting.populate`, fix `SpikeSortingSelection`. For `SpikeSortingRecording.populate` one tier up, fix `SpikeSortingRecordingSelection`. They're different tables with different PKs — don't restrict the wrong one.
- **`reserve_jobs=True`** can mask which key actually died. If after the fix your error log still names a sorter you didn't ask for, check the `~jobs` table for stale errored entries from the original loose-dict run:

  ```python
  import datajoint as dj
  dj.Schema(SpikeSorting.database).jobs & {
      'table_name': SpikeSorting.table_name, 'status': 'error',
  }
  ```

  Inspect, then `delete_quick()` only the entries you intentionally want to retry.
- **Sister symptom on merge tables.** A similar silent-no-op affects `MergeMaster & {'nwb_file_name': ...}` (the master's heading is just `merge_id`); use `merge_restrict()` / `merge_get_part()` there. Different surface, same DataJoint mechanism.
