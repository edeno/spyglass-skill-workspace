# Is there a `fetch_nwb1()`?

**No — there's no such method on Spyglass tables.** The only fetch helper for NWB objects is `fetch_nwb`, and it always returns a list of NWB objects, regardless of how many rows the restriction matched. A single-row restriction gives you a list-of-one, and you index `[0]` — that's not a wart, it's the contract.

I want to flag the meta-point first since you asked about an API that I can't be sure exists from training alone: **don't take my word for it, verify against the installed Spyglass.** The cheapest way is `dir()` / `inspect`:

```python
from spyglass.lfp.v1.lfp import LFPV1   # or whatever table you're on
import inspect

# What fetch-shaped methods does the table actually have?
[m for m in dir(LFPV1) if "fetch" in m]
# expect: ['fetch', 'fetch1', 'fetch1_dataframe', 'fetch_nwb', ...] — no fetch_nwb1

# Read the real signature/body so you're not guessing:
print(inspect.getsource(LFPV1.fetch_nwb))
print(inspect.getsourcefile(LFPV1.fetch_nwb))   # tells you which mixin it came from
```

If `fetch_nwb1` were real, `dir(table)` would list it. It won't. The canonical implementation lives on the `SpyglassMixin` (around `src/spyglass/utils/mixins/fetch.py`, with a few specialized overrides in `spikesorting/`, `position/v1/position_dlc_selection.py`, `common/common_behav.py`, and the merge-table machinery in `utils/dj_merge_tables.py`). All of them return a `list`.

## The single-row idiom

The fix for the `[0]` annoyance is to make sure the restriction is unique, *then* index. There are two equivalent flavors:

```python
# (a) Use fetch1('KEY') to assert uniqueness, then fetch_nwb on that key:
key = (LFPV1 & {
    "nwb_file_name": "j1620210710_.nwb",
    "lfp_electrode_group_name": "CA1",
    "target_interval_list_name": "02_r1",
    # ... whatever else makes the row unique
}).fetch1("KEY")            # raises if 0 or >1 rows — that's the safety net
nwb = (LFPV1 & key).fetch_nwb()[0]

# (b) Inline once you've convinced yourself the restriction is unique:
nwb = (LFPV1 & key).fetch_nwb()[0]
```

`fetch1('KEY')` is the part doing the actual work: it raises `DataJointError` if the restriction matches zero or more than one row, so by the time you reach `fetch_nwb()[0]` you've already proven there's exactly one element in the list.

## Why no `fetch_nwb1` shorthand exists (and why that's deliberate)

When people reach for an imagined `fetch_nwb1()`, the underlying problem is almost always a **too-loose restriction**: the `&` clause survived more than one row, `fetch_nwb()` returned a list-of-N, and `[0]` silently picked an arbitrary element. A `fetch_nwb1()` that hid this would make the bug harder to notice, not easier. Forcing you to either call `fetch1('KEY')` first or eyeball the list length keeps the "is this restriction actually unique?" question visible.

So the rule of thumb:

- If you're tempted to write `fetch_nwb1()`, the real fix is upstream — tighten the restriction (or call `fetch1('KEY')`) so there's provably one row.
- The `[0]` after `fetch_nwb()` is correct and idiomatic; it's not a missing-feature smell.
- Anything I tell you about Spyglass internals is worth a 10-second `dir(table)` / `inspect.getsource(...)` check before you build on it — that's the verification primitive for "does this method exist, and what does it do?"
