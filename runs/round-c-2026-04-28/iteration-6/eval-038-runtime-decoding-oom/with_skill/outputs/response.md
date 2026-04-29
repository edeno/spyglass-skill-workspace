## Short answer

You don't need a bigger GPU. The 24 GiB f32 buffer (`(3M, 2k)` ≈ `n_time × n_state_bins`) fits comfortably in your 80 GiB A100 once you (a) chunk the time axis and (b) raise the JAX memory cap. Two independent knobs, use both.

## (1) Tune `DecodingParameters.decoding_kwargs`

The critical schema fact (and the most common footgun here): on `DecodingParameters`, `decoding_params` and `decoding_kwargs` are **sibling top-level attributes**, NOT one nested inside the other. Verified at `src/spyglass/decoding/v1/core.py:38-43`:

```text
decoding_param_name : varchar(80)
---
decoding_params : LONGBLOB        # model-init blob (classifier constructor kwargs)
decoding_kwargs = NULL : LONGBLOB # runtime kwargs reaching predict()/estimate_parameters()
```

If you nest `decoding_kwargs` inside `decoding_params` it gets silently swallowed by the constructor and you'll wonder why `n_chunks` had no effect.

Insert a new param row with chunking enabled, then re-select and re-populate:

```python
from spyglass.decoding import DecodingParameters
from spyglass.decoding.v1.clusterless import (
    ClusterlessDecodingSelection, ClusterlessDecodingV1,
)
from non_local_detector.models import ContFragClusterlessClassifier

DecodingParameters.insert1({
    'decoding_param_name': 'contfrag_clusterless_chunked',
    'decoding_params': vars(ContFragClusterlessClassifier()),  # model-init blob
    'decoding_kwargs': {                                       # SIBLING attr — top-level
        'n_chunks': 10,           # split the time axis: 24 GiB → ~2.4 GiB per chunk
        'cache_likelihood': False, # don't pin the full likelihood in device memory
    },
}, skip_duplicates=True)

selection_key = {
    'nwb_file_name': nwb_file_name,
    'waveform_features_group_name': features_group_name,
    'position_group_name': position_group_name,
    'decoding_param_name': 'contfrag_clusterless_chunked',
    'encoding_interval': encoding_interval_name,
    'decoding_interval': decoding_interval_name,
    'estimate_decoding_params': 0,  # see "Which branch?" below
}
ClusterlessDecodingSelection.insert1(selection_key, skip_duplicates=True)
ClusterlessDecodingV1.populate(selection_key)
```

### Which branch consumes the kwargs?

Verified in `src/spyglass/decoding/v1/clusterless.py`:

- The classifier itself is constructed once at line **287** with `ClusterlessDetector(**decoding_params)` — that's the model-init blob.
- Line **289** branches on `key["estimate_decoding_params"]`:
  - **`False` branch** (line 333+, the default *inference* path): calls `get_valid_kwargs(classifier, decoding_kwargs, logger)` to split the dict into `fit_kwargs` / `predict_kwargs`, then `classifier.fit(**fit_kwargs)` (line 338) and `classifier.predict(..., **predict_kwargs)` (line 358) per decoding interval. **This is where `n_chunks` / `cache_likelihood` are intended to land for normal decoding.**
  - **`True` branch** (line 320): calls `classifier.estimate_parameters(..., **decoding_kwargs)` — this re-runs **EM parameter estimation**, not normal inference. Only take this branch if you actually want to re-fit parameters; it's not an "inference with chunking" mode.

So Spyglass passes `decoding_kwargs` straight through to whichever method runs in `make_compute` (`predict()` for `estimate_decoding_params=False`, `estimate_parameters()` for `True`). The `non_local_detector` package is what ultimately accepts or rejects each kwarg name.

If `n_chunks` or `cache_likelihood` appears to be ignored or rejected, verify the kwarg names against your installed `non_local_detector` directly — don't trust prose, trust the signature:

```python
import inspect
from non_local_detector.models import ContFragClusterlessClassifier
c = ContFragClusterlessClassifier()
print(inspect.signature(c.predict))           # False branch (estimate_decoding_params=0)
print(inspect.signature(c.estimate_parameters))  # True branch (estimate_decoding_params=1)
```

If your installed version uses different kwarg names (e.g. `chunk_size` instead of `n_chunks`), adjust accordingly. Don't assume `estimate_parameters()` rejects them without checking — it may accept the same OOM knobs depending on version.

## (2) Raise the JAX memory cap

Independent of (1). Put this at the top of the populate script, **before any JAX import**:

```python
import os
os.environ['XLA_PYTHON_CLIENT_MEM_FRACTION'] = '0.95'  # default is 0.75
# now import spyglass / jax / non_local_detector
```

JAX/XLA pre-allocates a single pool of `MEM_FRACTION × total_GPU_mem` (60 GiB at the 0.75 default). Bumping to 0.95 gives the decoder ~76 GiB on the 80 GiB A100 before XLA's allocator starts refusing. Complementary to chunking — use both.

## What I'd do, in order

1. Set `XLA_PYTHON_CLIENT_MEM_FRACTION=0.95`, retry the existing run. If it now fits, you're done.
2. If still OOM, insert the `contfrag_clusterless_chunked` `DecodingParameters` row above with `n_chunks=10` and `cache_likelihood=False`, re-insert the selection row pointing at it, and re-populate.
3. If `n_chunks` looks ignored, `inspect.signature` the installed `non_local_detector` `predict()` to confirm the kwarg names and adjust.

## What NOT to do

- **Don't upgrade the GPU.** A 24 GiB intermediate inside an 80 GiB device is a chunking problem, not a hardware problem.
- **Don't nest `decoding_kwargs` inside `decoding_params`.** They're siblings; nesting silently drops the runtime kwargs.
- **Don't flip to `estimate_decoding_params=1` as a "chunking workaround"** without realizing it triggers an EM re-fit (`estimate_parameters`, line 320) — that's a different computation, not a memory-friendlier inference.
- **Don't reach for v0 sorted-spikes knobs** (`sorted_spikes_algorithm_params`, `block_size`, etc.) — those belong to the v0 sorted-spikes path and have nothing to do with `ClusterlessDecodingV1` JAX OOMs.
