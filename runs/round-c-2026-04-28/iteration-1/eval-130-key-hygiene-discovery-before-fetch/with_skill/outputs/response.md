# Fetching LFP — discovery first, then fetch

Your prompt is under-specified, and handing back a one-liner like
`(LFPV1 & {"nwb_file_name": nwb_file}).fetch1_dataframe()` would almost
certainly raise. Here's why, and the right shape.

## Why "the LFP for my session" isn't a unique row

`LFPV1` inherits its primary key from `LFPSelection` (see
[lfp_pipeline.md § Step 2](../../skills/spyglass/references/lfp_pipeline.md)
and `src/spyglass/lfp/v1/lfp.py`). The full PK is **five fields**:

- `nwb_file_name`
- `lfp_electrode_group_name`     (which electrodes — e.g. `"my_lfp_group"`, `"lfp_tets_j16"`)
- `target_interval_list_name`    (which epoch — e.g. `"02_r1"`)
- `filter_name`                  (e.g. `"LFP 0-400 Hz"`)
- `filter_sampling_rate`         (must match the raw rate — typically 20000 or 30000)

Restricting only by `nwb_file_name` will return one row per
(electrode group × interval × filter preset) populated for that
session. `fetch1_dataframe()` will then raise
`DataJointError: fetch1 should only be called on relations with exactly one tuple`
(this is Common Mistake #2 in the skill — partial-key + `fetch1`).

Separately: don't try to dodge that by going through the merge master
with a bare restriction either. `LFPOutput`'s only PK field is
`merge_id`, so `(LFPOutput & {"nwb_file_name": nwb_file})` silently
drops the unknown attribute and returns the *whole* `LFPOutput` table
(Common Mistake #6, "silent no-op on merge masters"). You must use
`LFPOutput.merge_get_part(...)` or `LFPOutput.merge_restrict(...)`.

## Discovery-first code

Run this first to see which LFPs were actually populated for your
session, then pick one and resolve it through the merge layer:

```python
from spyglass.lfp.v1 import LFPSelection
from spyglass.lfp import LFPOutput

nwb_file = "your_session_.nwb"   # <-- fill in (e.g. from Session.fetch('nwb_file_name'))

# 1. Enumerate populated LFP rows for this session.
candidates = (LFPSelection & {"nwb_file_name": nwb_file}).fetch(
    "KEY", as_dict=True
)
print(f"{len(candidates)} LFPSelection rows for {nwb_file}:")
for c in candidates:
    print(c)
# Each printed dict shows the full PK: lfp_electrode_group_name,
# target_interval_list_name, filter_name, filter_sampling_rate.

# 2. Pick the one you want. If you already know which electrode
#    group / interval / filter you populated, build the key
#    explicitly instead of indexing candidates[0].
chosen_key = candidates[0]   # or: {"nwb_file_name": ..., "lfp_electrode_group_name": ..., ...}

# 3. Cardinality check before fetch1 (skill feedback loop).
sel = (LFPSelection & chosen_key)
assert len(sel) == 1, f"Expected 1 row, got {len(sel)} — add more PK fields"

# 4. Resolve through the merge table — DO NOT use a bare
#    `(LFPOutput & chosen_key)` restriction; LFPOutput's only PK is
#    `merge_id`, so the upstream fields would silently no-op.
merge_key = LFPOutput.merge_get_part(chosen_key).fetch1("KEY")
lfp_df = (LFPOutput & merge_key).fetch1_dataframe()

print(f"LFP shape: {lfp_df.shape}")          # (n_samples, n_electrodes)
print(f"Sampling rate: {1/(lfp_df.index[1] - lfp_df.index[0]):.1f} Hz")
```

## What I need from you to give you the one-shot version

Tell me which combination you populated and I can collapse this to
the explicit key form:

- **Electrode group** (`lfp_electrode_group_name`) — the name you
  passed to `LFPElectrodeGroup.create_lfp_electrode_group(group_name=...)`.
- **Interval** (`target_interval_list_name`) — typically an epoch name
  like `"02_r1"`. Discover with
  `(IntervalList & {"nwb_file_name": nwb_file}).fetch("interval_list_name")`.
- **Filter** (`filter_name`, `filter_sampling_rate`) — almost always
  `("LFP 0-400 Hz", 30000)` for a 30 kHz raw recording, or
  `("LFP 0-400 Hz", 20000)` at 20 kHz. Derive the rate from the raw:
  `int(np.round((Raw & {"nwb_file_name": nwb_file}).fetch1("sampling_rate")))`.

Once those four are known, the explicit form is a drop-in for
step 2 above (no enumeration needed):

```python
chosen_key = {
    "nwb_file_name": nwb_file,
    "lfp_electrode_group_name": "my_lfp_group",
    "target_interval_list_name": "02_r1",
    "filter_name": "LFP 0-400 Hz",
    "filter_sampling_rate": 30000,         # match raw rate; verify via Raw
}
merge_key = LFPOutput.merge_get_part(chosen_key).fetch1("KEY")
lfp_df = (LFPOutput & merge_key).fetch1_dataframe()
```

## Sanity checks worth running

- `len(LFPSelection & {"nwb_file_name": nwb_file})` — if 0, you
  haven't populated yet; see the canonical example in
  [lfp_pipeline.md](../../skills/spyglass/references/lfp_pipeline.md)
  for the `LFPElectrodeGroup` → `LFPSelection.insert1` →
  `LFPV1.populate(key)` flow.
- `len(LFPV1 & chosen_key)` — should equal 1 once `LFPV1.populate(...)`
  has run for that exact key. If `LFPSelection` has the row but
  `LFPV1` does not, populate didn't complete.
- `chosen_key in (LFPOutput.LFPV1 & chosen_key)` (i.e. that part
  table has a row) — confirms the merge entry was registered.
  `merge_get_part` will raise if not.

For the broader "before-fetch1, count first" pattern this is an
instance of, see
[feedback_loops.md § Pre-`fetch1()` cardinality check](../../skills/spyglass/references/feedback_loops.md#pre-fetch1-cardinality-check)
and Common Mistake #2 / #6 in the skill.
