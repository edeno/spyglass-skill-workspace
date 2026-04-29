# Why your `fetch_results` returns rows but your labmate's is empty

If you both "ran the same selection + populate on `j1620210710_.nwb`", the
empirical fact that one of you gets data and the other gets `[]` is itself
proof that your two pipeline states are *not* identical. The phrase "the
same" almost always papers over one of a small number of real differences.
Don't commit to a single cause yet — diff the state, then conclude.

Below are the most likely state-level differences, in roughly the order I'd
check them, plus the concrete diagnostics for each.

## 1. Different `params_name` on the selection

DataJoint pipelines almost always look like

```
ParamsTable  →  Selection (FK to params + FK to source nwb/key)  →  Computed/Populated
```

When you say "same selection", you probably mean "same prompt-level
parameter values". But the *Selection* row keys on `params_name`, not on
the parameter values themselves. Two users can each insert a params row
with different names that contain numerically identical contents — or
identical names that contain different contents — and end up restricting
to different Selection rows.

**Diagnose:** for each user's session, run

```python
(Selection & key).fetch(as_dict=True)            # what selection row was picked?
(ParamsTable & {'params_name': <that name>}).fetch1('params')   # contents
```

side by side and diff both the `params_name` and the params blob. If the
names differ, the rest of the pipeline diverges from there. If the names
are equal but contents differ, one of you inserted/overwrote params at
some point.

## 2. Your labmate's Selection row hasn't been populated (or populate skipped it)

`fetch_results` on the *Computed* (downstream) table returns empty when
the matching downstream row simply doesn't exist. That happens any time:

- The `populate()` call was restricted differently (e.g. they passed a
  more specific key, or ran on a stale connection that filtered out the
  row).
- `populate()` raised inside `make()` and got swallowed by `suppress_errors=True` /
  reserve-jobs logic, leaving an entry in the `~jobs` / `schema.jobs` table
  rather than a successful Computed row.
- They ran `populate()` against a different schema / virtual module
  (different prefix, different DataJoint host).

**Diagnose:**

```python
# Was the downstream row actually written?
(ComputedTable & key).fetch(as_dict=True)        # empty here = nothing to fetch_results

# Did populate fail and get logged?
schema.jobs & {'table_name': '__computed_table'} # check error_message / status

# What schema host are you each pointing at?
import datajoint as dj
print(dj.config['database.host'], dj.config['database.user'])
```

If theirs is empty here, the disagreement is not in `fetch_results` at
all — it's that the upstream `make()` didn't run for them. Note that
`cautious_delete` does NOT enter into this: it only gates DELETEs, not
inserts/populates, so it cannot explain a missing Computed row.

## 3. Different upstream restriction / different source rows

A Selection key like `{'nwb_file_name': 'j1620210710_.nwb', 'params_name': 'default'}`
is rarely the *full* primary key of the Selection. Most Spyglass
selection tables also key on an upstream identifier — for example a
merge UUID from a position pipeline, a `sort_group_id`, a
`SpikeSortingRecording` UUID, an interval list name, a `nwb_object_id`.
Two users can resolve the *same prompt* to different upstream rows
because:

- One inserted a fresh `PositionGroup` / `DLCPosV1` / `SpikeSortingRecording`
  and the merge table now points at a new merge_id; the other still has
  the old one.
- Interval list names overlap textually but were redefined.
- Re-running an upstream populate created a second Computed row with a
  new UUID, so a "latest"-style restriction picks different rows for
  each user.

**Diagnose:** dump the full primary key of the Selection row each of you
hits, not just the partial restriction you typed:

```python
(Selection & key).fetch('KEY')                   # full PK dicts
```

and walk one level upstream of each — `Selection.parents()` /
`dj.Diagram(Selection)` — comparing the upstream PKs. If a merge_id or
SpikeSortingRecording UUID differs, the rest is mechanical: same
`fetch_results` call hits a populated row for you and an unpopulated (or
nonexistent) row for them.

## 4. Environment / package-version drift between your two installs

Spyglass actually records the populate-time environment per row. The
`common.UserEnvironment` table (in `src/spyglass/common/common_user.py`)
stores an `env` blob keyed by `env_id`, and `SpyglassMixin` writes the
`env_id` into rows it inserts. So you don't have to guess at "are we on
the same versions" — you can fetch and diff the actual env that produced
each row.

**Diagnose:**

```python
from spyglass.common.common_user import UserEnvironment

# Pull each user's env blob
my_env_id    = (ComputedTable & my_key).fetch1('env_id')      # if present
their_env_id = (ComputedTable & their_key).fetch1('env_id')

my_env    = (UserEnvironment & {'env_id': my_env_id}).fetch1('env')
their_env = (UserEnvironment & {'env_id': their_env_id}).fetch1('env')

# Diff them, and also diff against your *currently running* interpreter:
import sys, json
print(sys.version)
# pip freeze / conda env export captured into a dict, then dict-diff
```

A real version delta (different `spyglass-neuro`, `spikeinterface`,
`pynwb`, `datajoint`, numpy, even Python minor version) can change
`make()` behavior — different defaults, different output shape, a
silently-skipped branch, or in the worst case a populate that "succeeds"
but writes nothing because an upstream signature changed. This is also
the right place to catch the "they ran it months ago on an old version"
case.

(If you also want to confirm your *running* env will reproduce theirs:
`conda env export --from-history` / `pip freeze` and compare against the
`env` blob.)

## First thing to actually do

Before debugging anything fancier:

```python
# Have each user run, in their own Python session:
print((Selection & key).fetch(as_dict=True))
print((ComputedTable & key).fetch(as_dict=True))
print((UserEnvironment & (ComputedTable & key)).fetch1('env_id'))  # if any
```

and paste both outputs side by side. Almost always one of three things
jumps out immediately: a different `params_name`, a different upstream
PK in the Selection row, or a Computed row that exists for one of you
and not the other. Once you see *which* of those it is, the fix is
obvious; guessing before that is just gambling.

## What is NOT the cause

- **`cautious_delete`**: it's a delete-time safety gate (blocks
  cross-user deletes / deletes with downstream dependents). It does not
  block writes, does not block `populate()`, and cannot make
  `fetch_results` return empty. Rule it out and move on.
- **"Spyglass must be deterministic so the states must be identical"**:
  the empty fetch is itself the disproof. Trust the symptom.
