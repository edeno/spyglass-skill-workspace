# Why your `sorter='mountainsort4'` restriction was silently ignored

Short answer: Spyglass isn't ignoring your kwarg, but DataJoint *is* — silently — because the dict you passed doesn't contain any **primary-key** attribute of `SpikeSortingSelection`. The `populate(restriction)` call then degenerates into "populate everything that hasn't been computed yet," which on your DB happens to include a row whose `sorter` is `kilosort2`. That row is what blew up.

This is a generic DataJoint behavior, not a Spyglass quirk — but it bites hardest in Spyglass v1 pipelines because almost every `*V1` Selection table uses a synthetic UUID primary key and pushes the human-readable identifiers (`nwb_file_name`, `sorter`, `interval_list_name`, …) into secondary attributes.

---

## What your call actually did

Look at `SpikeSortingSelection` in `spyglass/spikesorting/v1/sorting.py`:

```python
class SpikeSortingSelection(SpyglassMixin, dj.Manual):
    definition = """
    # Processed recording and spike sorting parameters. See `insert_selection`.
    sorting_id: uuid
    ---
    -> SpikeSortingRecording
    -> SpikeSorterParameters
    -> IntervalList
    """
```

The **only** primary-key attribute is `sorting_id`. Everything else (`nwb_file_name`, `sorter`, `sorter_param_name`, `interval_list_name`, `recording_id`, …) lives below the `---` line — it's a *secondary* attribute, reached by joining through foreign keys.

Now consider what `SpikeSorting.populate(restriction)` does internally. `dj.Computed.populate` iterates `self.key_source - self`, where `key_source` is, by default:

```python
# DataJoint's autopopulate.py, simplified
@property
def key_source(self):
    parents = self.parents(primary=True, as_objects=True)
    # ... for a single-parent table:
    return parents[0].proj()
```

The crucial bit is `.proj()` with no args. That projects the parent **down to its primary key only**. So for `SpikeSorting`, whose only parent is `SpikeSortingSelection`:

```python
SpikeSorting.key_source  # heading == {sorting_id}  -- nothing else
```

When you then call `populate({'nwb_file_name': '...', 'sorter': 'mountainsort4'})`, DataJoint applies that dict as a restriction to `key_source`:

```python
key_source & {'nwb_file_name': '...', 'sorter': 'mountainsort4'}
```

DataJoint's `&` operator, when given a `dict`, **silently drops keys that are not in the relation's heading**. The heading here is `{sorting_id}`. Neither `nwb_file_name` nor `sorter` is in it. So both keys are discarded, the restriction becomes `& {}` (a no-op), and `populate` walks every un-computed `sorting_id` in `SpikeSortingSelection` — including ones inserted with `sorter='kilosort2'`. The first kilosort2 row hits the spikeinterface sorter-dispatch and raises `Exception: The sorter kilosort2 is not installed`.

This is **not** the same behavior as `fetch1`. If you had written

```python
SpikeSortingSelection.fetch1({'nwb_file_name': '...', 'sorter': 'mountainsort4'})
```

DataJoint would have raised because `fetch1` requires exactly one row. But `populate` happily iterates "everything matching" — and "everything matching a no-op restriction" is "everything" — so it fails late, deep inside a worker, with an error message that has nothing obvious to do with restriction filtering.

---

## The fix: resolve the restriction *first*, then hand `populate` a PK-only key

The general pattern is: restrict against the **full Selection table** (whose heading *does* include the secondary attrs you want to filter on), then pass the resulting primary-key dict to `populate`.

For a single sorting:

```python
sel_key = (SpikeSortingSelection
           & {'nwb_file_name': 'j1620210710_.nwb',
              'sorter': 'mountainsort4'}).fetch1('KEY')
SpikeSorting.populate(sel_key)
```

`fetch1('KEY')` returns the primary-key dict (here just `{'sorting_id': <uuid>}`). That key *is* in `key_source`'s heading, so `populate` will restrict correctly and process exactly the row you intended.

For multiple matching rows (say, every mountainsort4 sorting for that NWB file):

```python
sel = (SpikeSortingSelection
       & {'nwb_file_name': 'j1620210710_.nwb',
          'sorter': 'mountainsort4'})
SpikeSorting.populate(sel.proj())   # .proj() -> PK-only restriction
# or equivalently:
SpikeSorting.populate(sel.fetch('KEY'))   # list of PK dicts
```

`sel.proj()` reduces `sel` to just its primary key heading (`{sorting_id}`), and DataJoint will use that as the restriction — no silent drops because every attribute in the restriction *is* in `key_source`'s heading.

If `fetch1('KEY')` itself raises ("more than one tuple") that's a *useful* error: it means your `nwb_file_name + sorter` filter actually matches several Selection rows, and you need to narrow further (e.g., add `interval_list_name` or `sorter_param_name`).

---

## This generalizes to every `*V1.populate(...)` in Spyglass

The synthetic-UUID-as-sole-PK pattern is everywhere in v1:

- `LFPV1` ← `LFPSelection` (PK is some UUID/`merge_id`-style field; `nwb_file_name`, `filter_name`, `target_interval_list_name` are secondary)
- `TrodesPosV1` ← `TrodesPosSelection`
- `DLCPosV1` ← `DLCPosSelectionV1`
- `RippleTimesV1` ← `RippleParameters`/`RippleSelection`
- `SortedSpikesGroup`, `SortedSpikesDecodingV1`, `ClusterlessDecodingV1`, …

Whenever you find yourself typing

```python
SomeV1.populate({'nwb_file_name': ..., 'something_human_readable': ...})
```

stop and check the Selection table definition. If those attributes are below the `---`, that call is a no-op restriction and you're about to populate the whole backlog. The same `(Selection & friendly_dict).fetch1('KEY')` (or `.proj()`) detour fixes it across the board.

A defensive habit: when in doubt, restrict the Selection table and inspect what you got *before* calling `populate`:

```python
sel = SpikeSortingSelection & {'nwb_file_name': '...', 'sorter': 'mountainsort4'}
print(len(sel))        # sanity-check the count
sel                    # in a notebook, see the actual rows
SpikeSorting.populate(sel.proj())
```

That two-line guard would have surfaced the `kilosort2` row before any sorter ran.

---

## TL;DR

- `SpikeSortingSelection`'s only PK is `sorting_id` (uuid).
- `SpikeSorting.key_source` defaults to `SpikeSortingSelection.proj()` — heading is just `{sorting_id}`.
- `populate({'nwb_file_name': ..., 'sorter': ...})` → DataJoint's `&` silently drops dict keys that aren't in the heading → restriction collapses to a no-op → `populate` iterates every unprocessed Selection row, including kilosort2 ones.
- Unlike `fetch1`, `populate` does **not** raise on a loose dict; it just quietly does the wrong thing.
- Fix: `SpikeSorting.populate((SpikeSortingSelection & friendly_dict).fetch1('KEY'))`, or `.proj()` for multi-row.
- Same fix applies to every other `*V1.populate(...)` whose Selection PK is a synthetic UUID.
