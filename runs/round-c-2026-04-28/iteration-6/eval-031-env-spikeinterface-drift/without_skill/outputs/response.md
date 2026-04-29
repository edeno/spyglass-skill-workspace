# `AttributeError: module 'spikeinterface' has no attribute 'WaveformExtractor'`

Short version: this is almost certainly a SpikeInterface API drift, not a Spyglass bug. `WaveformExtractor` was the central object for spike-sorting post-processing in SpikeInterface 0.9x; it was deprecated and then **removed** in the 0.100/0.101 series, replaced by the new `SortingAnalyzer` API. If your environment was just upgraded past that boundary, anything (Spyglass included) that does `si.WaveformExtractor(...)` or `from spikeinterface import WaveformExtractor` will blow up at import.

But before naming a fix, I want to verify that's actually what happened — there are a couple of other things that produce a similar-looking error, and the right remediation depends on which one.

## Questions to confirm the diagnosis

1. **Did anything in the env change since "last week"?** Specifically:
   - Did you (or pip/conda/uv) upgrade `spikeinterface`?
   - Did you upgrade Spyglass itself, or anything that pulls SpikeInterface as a dep — e.g. `mountainsort5`, `spikeinterface-gui`, `probeinterface`, a sibling sorter wrapper, a Kachery/SortingView pin, even a fresh `pip install` of a package that quietly upgraded SI?
   - Did you rebuild the env (new venv / new conda env / `uv sync` after a lockfile bump)?
   - Did the cluster/shared-env admin update something for you?
2. What do these report?
   ```bash
   python -c "import spikeinterface; print(spikeinterface.__version__, spikeinterface.__file__)"
   python -c "import spyglass; print(spyglass.__version__)"
   pip show spikeinterface spyglass-neuro | grep -E '^(Name|Version|Location)'
   ```
3. Full traceback please — the line that actually references `WaveformExtractor` tells us whether it's Spyglass code, your own code, or a third-party dependency triggering it.

## Why I'm 95% confident before you even answer

`WaveformExtractor` existed for years and was a stable name. The *only* realistic way to land on `AttributeError: module 'spikeinterface' has no attribute 'WaveformExtractor'` in a previously-working env is a SpikeInterface version that no longer exposes it. The SI team did this transition in two phases:

- **0.100.x**: `WaveformExtractor` deprecated, `SortingAnalyzer` introduced as the replacement.
- **0.101.x and later**: `WaveformExtractor` removed entirely. This is what your error says.

So either (a) something bumped SI past Spyglass's supported range, or (b) the env was rebuilt and the resolver picked a newer SI than what Spyglass pins.

## The fix

**Don't** monkey-patch Spyglass to use `SortingAnalyzer` and don't edit Spyglass's parameter dicts to match the new SI API surface — Spyglass's spike-sorting code (the v1 pipeline in particular) is written against the pinned SI range, and the migration is non-trivial (sorting-analyzer extensions, units API, exporter changes, qc metric naming, …). Patching downstream will create a maintenance burden and probably break other tables.

**Do** pin SpikeInterface back into the range Spyglass actually supports. The source of truth for that pin is **Spyglass's `pyproject.toml`** — open it in the version of Spyglass you have installed and look at the `spikeinterface` line under `[project] dependencies`. It will look something like `spikeinterface>=0.99.x,<0.100` (the exact upper bound depends on your Spyglass version, which is why I'm not quoting a specific number — read it from the file you actually have).

Then, in your isolated env (not base):

```bash
# inside the conda env / venv / uv project that runs Spyglass
pip install "spikeinterface>=0.99.1,<0.100"   # or whatever pyproject.toml says
```

Adjust the bounds to match what you read out of `pyproject.toml`. If `mountainsort5` or another sorter wrapper insists on a newer SI, that's a real conflict — resolve it by pinning the sorter to a version compatible with Spyglass's SI range, not by letting it pull in 0.101.

Verify:

```bash
python -c "import spikeinterface as si; print(si.__version__); print(hasattr(si, 'WaveformExtractor'))"
```

You want a 0.99.x version and `True`.

## A note on v0 vs v1

If you're running the older `spikesorting.v0` code path and someone suggests "just downgrade to v0 and stay there" — don't. The v0 pipeline is not kept in sync with modern SpikeInterface and is on its way out. If you have a real reason to track newer SI (e.g. a feature only in `SortingAnalyzer`), the correct migration is **forward to v1**, not backward to v0. For right now, though: pin SI back into the supported range and you'll be running again immediately.

## Prevention

Once you're back on your feet:

- Pin your env. `pip freeze > requirements.lock`, or use `uv` with a lockfile, or a conda env file with versions. The next "transparent upgrade" will not be transparent.
- Don't install Spyglass adjacencies into the base/system Python — use a dedicated env so resolver decisions are local.
- When upgrading Spyglass, re-read its `pyproject.toml` and bump SI to match deliberately, not as a side-effect of `pip install -U <something>`.

Send me the answers to the questions above (especially the version printout and the full traceback) and I can confirm the diagnosis before you change anything.
