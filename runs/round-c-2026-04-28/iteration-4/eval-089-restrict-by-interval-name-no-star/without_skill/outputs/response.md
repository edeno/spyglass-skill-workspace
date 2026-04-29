# Restricting sessions by `SpikeSortingRecording` interval list — without `*` joins

## Short answer

Use the `&` restriction operator with a dict that names the
`interval_list_name`, then project to the session key:

```python
from spyglass.spikesorting.v1 import SpikeSortingRecording
from spyglass.common import Session

interval = "02_r1"  # whatever your interval list is called

# rows of SpikeSortingRecording populated for that interval
ssr_for_interval = SpikeSortingRecording & {"interval_list_name": interval}

# the matching sessions (Session is upstream of SpikeSortingRecording)
sessions = Session & ssr_for_interval.proj()
sessions.fetch("nwb_file_name")
```

That's it — no `*` (cross/inner join) anywhere. Each step is a
restriction (`&`) and a projection (`.proj()`).

## Why this works

In DataJoint:

- `A & B` restricts rows of `A` to those whose primary-key attributes
  match at least one row in `B`. This is a *semijoin*, not a join —
  the schema of `A` is unchanged, no columns from `B` leak in, and
  duplicates aren't introduced.
- `B.proj()` (with no args) keeps only `B`'s primary key. Restricting
  `Session` by `ssr_for_interval.proj()` says "keep sessions whose PK
  appears in the PK of those `SpikeSortingRecording` rows."

Because `SpikeSortingRecording`'s primary key inherits from `Session`
(via `Nwbfile` → `IntervalList` → `SpikeSortingRecordingSelection` →
`SpikeSortingRecording`), the `nwb_file_name` attribute is shared, so
the semijoin matches on it without you needing to spell the join out.

## Variants

**1. Combine with other restrictions on the same table:**

```python
ssr_for_interval = SpikeSortingRecording & {
    "interval_list_name": "02_r1",
    "team_name": "ms_team",          # any other PK/secondary attrs
}
sessions = Session & ssr_for_interval.proj()
```

**2. Restrict by a list of interval names** (use a list of dicts or
a SQL string):

```python
intervals = ["02_r1", "04_r2"]
ssr = SpikeSortingRecording & [{"interval_list_name": n} for n in intervals]
# or:
ssr = SpikeSortingRecording & 'interval_list_name in ("02_r1","04_r2")'

sessions = Session & ssr.proj()
```

**3. Just want the distinct `nwb_file_name`s, not the `Session` rows?**
You can fetch directly from the projection:

```python
nwb_files = (SpikeSortingRecording & {"interval_list_name": "02_r1"}) \
              .fetch("nwb_file_name")
set(nwb_files)   # dedupe
```

This skips even the final `Session &` step if you don't need the
session metadata columns.

**4. Sessions where `SpikeSortingRecording` was actually populated**
(as opposed to merely *selected*) — that's exactly what the snippet
above gives you, because `SpikeSortingRecording` is the populated
table. If you want the *selection* surface instead, restrict
`SpikeSortingRecordingSelection` the same way.

## What to avoid

- `Session * SpikeSortingRecording & {...}` — that's a `*` join, which
  the question rules out and which also blows up the row count to
  one row per recording per session.
- `(SpikeSortingRecording & {...}).fetch("KEY")` followed by
  `Session & keys` — works, but it round-trips the keys through Python
  needlessly. The `.proj()` form keeps everything as a single SQL
  query.

## Sanity checks worth doing

- `len(ssr_for_interval)` > 0 before restricting `Session`, so you can
  tell "no sessions match" apart from "the interval name is
  misspelled".
- `ssr_for_interval.heading.primary_key` to confirm the PK actually
  contains `nwb_file_name` (it does for `SpikeSortingRecording`, but
  this is the generic way to verify a semijoin will match on the
  attribute you expect).
- If you get more sessions than you expected, print
  `ssr_for_interval.fetch("nwb_file_name", "interval_list_name")`
  and eyeball the pairs — interval list names like `"01_s1"` /
  `"02_r1"` are per-session, so the same string can legitimately
  appear in many sessions.
