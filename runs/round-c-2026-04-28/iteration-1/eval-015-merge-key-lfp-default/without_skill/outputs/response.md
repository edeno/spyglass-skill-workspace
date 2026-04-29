# Getting the LFP `merge_id` for `j1620210710_`

In Spyglass, LFP outputs are funneled through the `LFPOutput` merge table
(`spyglass.lfp.lfp_merge.LFPOutput`). To get a scalar `merge_id`, you go
through the part table for the source pipeline you used (almost certainly
`LFPOutput.LFPV1` for a freshly-computed LFP), restrict it on the upstream
key that produced your entry, and then ask the master for the matching
`merge_id`.

The "standard lab wideband filter" in Spyglass is registered by
`FirFilterParameters.create_standard_filters` under the name
**`'LFP 0-400 Hz'`** — a low-pass with passband edge at 400 Hz and
stopband at 425 Hz. Note that this filter is registered for **two**
sampling rates (20 kHz and 30 kHz raw), and `FirFilterParameters` keys
on `(filter_name, filter_sampling_rate)`, so you generally need both
to nail down a unique row.

## Step 1 — sanity-check the filter row

```python
from spyglass.common.common_filter import FirFilterParameters

(FirFilterParameters
 & {'filter_name': 'LFP 0-400 Hz'}
).fetch('filter_name', 'filter_sampling_rate', as_dict=True)
# -> typically two rows, one at 20000 and one at 30000
```

For Frank-lab Trodes recordings the raw rate is 30 kHz, so you'll most
likely want `filter_sampling_rate=30000`. If you're unsure, run the
discovery in step 2 below and let the part table tell you which rate
was actually used for this NWB file.

## Step 2 — discover the candidate LFPV1 row(s)

Restrict the part table on the NWB file and the filter name and inspect
what comes back before committing to a key:

```python
from spyglass.lfp.lfp_merge import LFPOutput

candidates = (LFPOutput.LFPV1
    & {'nwb_file_name': 'j1620210710_.nwb',
       'filter_name': 'LFP 0-400 Hz'}
).fetch('lfp_electrode_group_name',
        'target_interval_list_name',
        'filter_sampling_rate',
        'merge_id',
        as_dict=True)

for c in candidates:
    print(c)
```

If exactly one row comes back, you can read `merge_id` directly from it.
If more than one row comes back (e.g. multiple electrode groups, or both
the 20 kHz and 30 kHz filter rows are populated), you need to disambiguate
by `lfp_electrode_group_name` and/or `target_interval_list_name` and/or
`filter_sampling_rate` before fetching.

## Step 3 — fetch the scalar `merge_id` via `merge_get_part`

Once you know the full upstream key, use `LFPOutput.merge_get_part` —
this is the canonical merge-table accessor and is a classmethod, so you
call it on `LFPOutput` itself, not on a restricted relation:

```python
key = {
    'nwb_file_name': 'j1620210710_.nwb',
    'filter_name': 'LFP 0-400 Hz',
    'filter_sampling_rate': 30000,                  # required for uniqueness
    'lfp_electrode_group_name': '<group_from_step_2>',
    'target_interval_list_name': '<interval_from_step_2>',
}

merge_id = LFPOutput.merge_get_part(key).fetch1('merge_id')
print(merge_id)
```

You can now pass `merge_id` (or, equivalently, `{'merge_id': merge_id}`)
into your downstream code — anything that takes an `LFPOutput` key,
`LFPOutput.merge_restrict(...)`, `LFPOutput & {'merge_id': merge_id}`,
`fetch_nwb`, etc.

## Things to watch out for

- **Don't guess `filter_name='default'`.** The standard low-pass is
  literally registered as `'LFP 0-400 Hz'`. Always check
  `FirFilterParameters.fetch('filter_name', 'filter_sampling_rate')` if
  you're unsure rather than guessing a string.
- **`filter_name` alone is not unique** in `FirFilterParameters` — the
  primary key is `(filter_name, filter_sampling_rate)`. If you restrict
  only on `filter_name`, you may match both the 20 kHz and the 30 kHz
  registration of `'LFP 0-400 Hz'`.
- **`merge_get_part` is a classmethod.** Call it on the merge class
  (`LFPOutput.merge_get_part(key)`), not on a restricted relation
  (`(LFPOutput & restriction).merge_get_part(...)` is not the intended
  use). It dispatches to the appropriate part table based on the source.
- **If `fetch1` errors with "fetch1 should only return one tuple"**, the
  restriction is still under-specified — go back to step 2 and look at
  the candidates. Common culprits are multiple
  `lfp_electrode_group_name` values for the same NWB file, or both raw
  sampling rates being represented.
- **If `fetch1` errors with "fetch1 should return one tuple, returned 0"**,
  the LFP hasn't been populated yet for this combination, or one of the
  string values is misspelled (case-sensitive — `'LFP 0-400 Hz'` with the
  exact spaces and capitalization). Check
  `(LFPV1 & {'nwb_file_name': 'j1620210710_.nwb'}).fetch('KEY')` to see
  what actually exists.
- **Legacy `CommonLFP` source.** If this session was ingested via the
  legacy `common_ephys.LFP` pipeline rather than `LFPV1`, you'd use
  `LFPOutput.CommonLFP` instead of `LFPOutput.LFPV1`. For a
  recently-processed file, `LFPV1` is the right part table.
