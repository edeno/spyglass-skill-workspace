# Getting the LFP `merge_id` for `j1620210710_`

Short answer: you cannot uniquely pin an `LFPOutput` row by `(nwb_file_name, filter_name)` alone, so I'll show you the safe shape and what extra fields you need.

## Why "the standard wideband filter" isn't enough on its own

The canonical `'LFP 0-400 Hz'` filter ships in `FirFilterParameters` for **both 20 kHz and 30 kHz** raw rates — `create_standard_filters()` inserts both rows (`src/spyglass/common/common_filter.py:582-595`):

```python
# common_filter.py
self.add_filter("LFP 0-400 Hz", 20000, "lowpass", [400, 425], "standard LFP filter for 20 KHz data")
self.add_filter("LFP 0-400 Hz", 30000, "lowpass", [400, 425], "standard LFP filter for 30 KHz data")
```

`FirFilterParameters` keys on `(filter_name, filter_sampling_rate)`, so `filter_name='LFP 0-400 Hz'` does not point at a single filter row. `LFPSelection` then keys on `(nwb_file_name, lfp_electrode_group_name, target_interval_list_name, filter_name, filter_sampling_rate)` — five PK fields, only one of which you've given me. Restricting `LFPOutput.LFPV1` by just `nwb_file_name` + `filter_name` will typically match more than one row, and `merge_get_part(...).fetch1('merge_id')` will then raise.

There is no row in `FirFilterParameters` named `'default'` — don't guess that. Use `'LFP 0-400 Hz'` (the actual canonical name) or discover via `FirFilterParameters.fetch('filter_name', 'filter_sampling_rate')`.

## Recommended shape: discover, then resolve

If you don't already know the raw sampling rate / electrode group / interval that was used, list the candidates first, pick the right one, and feed the full key to `merge_get_part`:

```python
from spyglass.common import FirFilterParameters
from spyglass.lfp import LFPOutput

# Optional: confirm the canonical filter name(s) actually present at your site
FirFilterParameters.fetch('filter_name', 'filter_sampling_rate')

# 1. List all populated LFPV1 entries for this session + filter name.
candidates = (LFPOutput.LFPV1
    & {'nwb_file_name': 'j1620210710_.nwb',
       'filter_name': 'LFP 0-400 Hz'}
).fetch('lfp_electrode_group_name',
        'target_interval_list_name',
        'filter_sampling_rate',
        as_dict=True)

for i, c in enumerate(candidates):
    print(i, c)

# 2. Pick the one that matches the electrode group / interval / raw rate
#    you intended (e.g. the wideband group, the run interval, 30000 Hz raw).
chosen = candidates[i]   # fill in i after inspection

# 3. Resolve the scalar merge_id. Note merge_get_part is a CLASSMETHOD —
#    call it on the class, never on (LFPOutput & key).merge_get_part(),
#    which silently discards the &.
merge_id = LFPOutput.merge_get_part({
    'nwb_file_name': 'j1620210710_.nwb',
    'filter_name': 'LFP 0-400 Hz',
    **chosen,
}).fetch1('merge_id')
```

## Direct shape if you already know the full key

If you know the wideband electrode group name, the interval, and the raw rate (typical: 30 kHz raw on this session), you can skip the discovery step:

```python
merge_id = LFPOutput.merge_get_part({
    'nwb_file_name': 'j1620210710_.nwb',
    'lfp_electrode_group_name': '<your wideband group>',
    'target_interval_list_name': '<your interval, e.g. "02_r1">',
    'filter_name': 'LFP 0-400 Hz',
    'filter_sampling_rate': 30000,   # use 20000 if the raw recording is 20 kHz
}).fetch1('merge_id')
```

If `merge_get_part` raises `ValueError: Found multiple potential parts` or `fetch1` raises "expected one tuple", the restriction is still under-specified — go back to the discovery shape above. If it raises `Found 0 potential parts: []`, then either (a) `LFPV1` was populated but never inserted into `LFPOutput.LFPV1`, or (b) one of the field values is misspelled / the LFP wasn't populated for this `(group, interval, filter_sampling_rate)` combination yet.

## A couple of things I deliberately did NOT do

- I did **not** write `(LFPOutput & {'nwb_file_name': 'j1620210710_.nwb'}).fetch1('merge_id')`. The merge master's only PK field is `merge_id`, so DataJoint silently drops the `nwb_file_name` restriction and you get back the whole table.
- I did **not** call `merge_get_part` as `(LFPOutput & key).merge_get_part()`. It's a classmethod — the `& key` would be silently discarded.
- I did **not** assume `filter_name='default'`. The canonical name is `'LFP 0-400 Hz'`; verify with `FirFilterParameters.fetch('filter_name', 'filter_sampling_rate')` if unsure.

If you tell me the electrode group name, the interval, and the raw rate (or paste the output of the `candidates` list), I can hand you back a single fully-specified `merge_get_part(...)` call.
