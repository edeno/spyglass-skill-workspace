# `LFPSelection.target_sampling_rate`

## What it controls

`target_sampling_rate` (Hz) is the sampling rate that `LFPV1.make()`
will **decimate the filtered LFP down to** before storing it. It is
the rate of the LFP stream you (and every downstream consumer)
actually read back via `(LFPOutput & merge_key).fetch1_dataframe()`.

It is one of three sampling-rate fields that interact strictly in
the LFP pipeline:

| Field | What it must equal |
| ----- | ------------------ |
| `filter_sampling_rate` | The actual sampling rate of the input the filter is applied to — i.e. the raw rate (typically 20 kHz or 30 kHz, derived from `Raw.fetch1("sampling_rate")`). `FirFilterParameters` keys on `(filter_name, filter_sampling_rate)`, so a filter named for one rate won't apply to a stream at another rate. |
| `target_sampling_rate` | The output rate of `LFPV1`. Spyglass's canonical default is **1000 Hz** (paired with the shipped `"LFP 0-400 Hz"` broadband filter). Must strictly exceed 2× the *filter*'s high cutoff (Nyquist on the way down). |
| Downstream `LFPBandSelection.filter_sampling_rate` | Must match the upstream `LFPV1.target_sampling_rate` — e.g. if `target_sampling_rate=1000`, the ripple-band filter must be registered with `fs=1000.0`. |

So `target_sampling_rate` is both (1) the rate of your stored LFP
and (2) the contract that *all* downstream band filters must match
in their own `filter_sampling_rate` and Nyquist budget.

## What goes wrong if it's too low for ripple-band analysis

A ripple-band filter is canonically `"Ripple 150-250 Hz"` with band
edges roughly `[140, 150, 250, 260]`. Two distinct things break,
roughly in this order of severity:

### 1. Aliasing — irrecoverable signal corruption

When `LFPV1` decimates from `filter_sampling_rate` (e.g. 30 kHz)
down to `target_sampling_rate`, the new Nyquist is
`target_sampling_rate / 2`. Any spectral content above that Nyquist
folds back ("aliases") into lower frequencies as ghost signal.

The shipped `"LFP 0-400 Hz"` filter has its passband out to 400 Hz,
so:

- **`target_sampling_rate = 1000` Hz** (canonical) → Nyquist
  500 Hz, which is **strictly above** the 400 Hz filter cutoff. No
  aliasing, full ripple band (150–250 Hz) preserved cleanly. Good.
- **`target_sampling_rate = 500` Hz** → Nyquist 250 Hz, right at
  the upper edge of the ripple band. Energy at 250–400 Hz from the
  broadband filter folds back to 100–250 Hz, **directly into the
  ripple band**, contaminating exactly the signal you care about.
- **`target_sampling_rate = 400` Hz** → Nyquist 200 Hz. The top
  half of the ripple band (200–250 Hz) is above Nyquist and is
  literally not representable; energy from 200–400 Hz aliases down
  into 0–200 Hz, again polluting the ripple band.
- **`target_sampling_rate = 300` Hz** → Nyquist 150 Hz, **below the
  entire ripple band**. The ripple band is gone, and the LFP you
  stored is contaminated with aliased ripple-band energy folded
  into lower bands. A subsequent `"Ripple 150-250 Hz"` filter at
  `fs=300` would be ill-defined (Nyquist violation in filter
  design) and, even if it ran, would not be operating on real
  150–250 Hz signal.

This is what the skill calls out as "the most common
mis-configuration": an arbitrary `target_sampling_rate` that
doesn't satisfy `target_sampling_rate > 2 × filter_high_cutoff`
aliases real signal into the passband, and **the corruption is
baked into the stored analysis NWB file** — re-running the band
stage cannot recover what was lost.

### 2. Downstream key/Nyquist mismatch — the populate fails (or finds nothing)

Even before you hit the math, the pipeline structure will reject
the configuration:

- `FirFilterParameters` is keyed on `(filter_name,
  filter_sampling_rate)`. Your ripple-band filter must be
  registered with `fs` equal to `LFPV1.target_sampling_rate`. If
  you set `target_sampling_rate=500`, you must register `"Ripple
  150-250 Hz"` at `fs=500.0`; the canonical 1 kHz registration
  won't match and `LFPBandV1.populate` will not find a matching
  filter row.
- The "high cutoff strictly below LFP-stream Nyquist" rule means
  any `target_sampling_rate ≤ 500` makes a 250 Hz ripple cutoff
  invalid by Nyquist — you cannot validly design a 150–250 Hz
  bandpass at fs ≤ 500 Hz. `scipy.signal` will either refuse or
  return a filter that doesn't do what its name says.
- `RippleLFPSelection.validate_key` further requires the band
  filter's `filter_name` to contain `"ripple"` (`ripple.py:46–50`),
  so you can't sidestep by renaming.

## Practical rule for ripple work

If you know you want ripples downstream, **leave
`target_sampling_rate=1000`** (the canonical default paired with
`"LFP 0-400 Hz"`). It satisfies:

- 1000 > 2 × 400 (no aliasing through the broadband filter), and
- 1000 / 2 = 500 > 250 (ripple-band high cutoff fits with
  headroom), and
- it matches the `fs=1000.0` that the conventional `"Theta 5-11
  Hz"` and `"Ripple 150-250 Hz"` filter rows use site-wide.

Anything below ~750 Hz starts eating into the ripple band's
Nyquist budget; anything at or below 500 Hz makes the ripple band
effectively unrecoverable from the stored LFP.

## Sources

- `skills/spyglass/references/lfp_pipeline.md` — "Nyquist note on
  filter/sampling-rate fields" (the three-field interaction rule),
  Canonical Example, and the band-filter registration showing
  `fs=1000.0` paired with `target_sampling_rate=1000`.
- `skills/spyglass/references/ripple_pipeline.md` — confirms the
  ripple band defaults (`"Ripple 150-250 Hz"`, band_edges
  `[140, 150, 250, 260]`) and the `RippleLFPSelection.validate_key`
  ripple-name guard at `ripple.py:46–50`.
- Skill-cited Spyglass source: `lfp/v1/lfp.py:72-75, 107-109`
  (LFPV1.make fetches raw rate, looks up `FirFilterParameters` by
  `filter_sampling_rate`); `common/common_filter.py:577`
  (`create_standard_filters` ships the 20 kHz / 30 kHz `"LFP 0-400
  Hz"` rows); `lfp/analysis/v1/lfp_band.py:25-26` (LFPBandSelection
  FK to `LFPOutput.proj(lfp_merge_id='merge_id')`).
