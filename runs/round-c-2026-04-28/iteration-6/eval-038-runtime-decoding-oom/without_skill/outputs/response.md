# JAX OOM in `ClusterlessDecodingV1.populate` — knobs before bigger GPU

Short version: no, you almost certainly don't need a bigger GPU. A 25.9 GB allocation on an 80 GB A100 means you have headroom — what's blowing up is JAX/XLA's *peak* allocation (the 24 GiB f32 buffer is `n_time x n_state x 4 bytes = 3e6 * 2e3 * 4 ≈ 24 GiB` for one big array, and JAX typically needs at least a couple of these alive simultaneously inside `predict`). Two independent levers to try, and they compose.

## (1) Chunk the time axis and skip caching the likelihood

The decoder in Spyglass v1 (both `ClusterlessDecodingV1` and `SortedSpikesDecodingV1`) wraps `non_local_detector`'s classifier. That classifier's `predict()` (and `estimate_parameters()`) accept runtime kwargs for memory control — most importantly:

- `n_chunks` — splits the time axis into N pieces and runs the forward/backward pass per chunk. With `n_chunks=10`, your 24 GiB peak buffer drops to roughly 2.4 GiB.
- `cache_likelihood=False` — by default the per-time-bin likelihood matrix can be retained on device for reuse; turning this off frees it once consumed.

In Spyglass v1, those are passed via the `decoding_kwargs` field on `DecodingParameters` — and crucially `decoding_kwargs` is a **separate top-level attribute** on the parameters row, *not* something you nest inside `decoding_params`. `decoding_params` is the **model-init** blob (constructor kwargs for the classifier — state transitions, environments, observation model, etc.). `decoding_kwargs` is the **runtime** blob that Spyglass forwards to whichever method `make_compute` ends up calling.

```python
from spyglass.decoding.v1.core import DecodingParameters

DecodingParameters.insert1(
    {
        "decoding_param_name": "clusterless_chunked",
        "decoding_params": {
            # ... your existing model-init kwargs (classifier ctor args) ...
        },
        "decoding_kwargs": {
            "n_chunks": 10,
            "cache_likelihood": False,
        },
    },
    skip_duplicates=True,
)
```

Then re-insert your `DecodingSelection` row pointing `decoding_param_name='clusterless_chunked'` and re-run `ClusterlessDecodingV1.populate(key)`.

A few notes on how those kwargs actually reach the math:

- Inside `ClusterlessDecodingV1.make_compute` (look at `src/spyglass/decoding/v1/clusterless.py`), the `estimate_decoding_params` flag selects which classifier method is called. With `estimate_decoding_params=False` (the default — normal inference), `decoding_kwargs` is forwarded into `classifier.predict(...)`. With `estimate_decoding_params=True`, it forwards into `classifier.estimate_parameters(...)`, which re-runs EM to *re-fit* HMM parameters (transition / initial-state) on this session — that's not what you want for a normal decode-for-inference run, so leave it `False`.
- The kwargs that `predict()` / `estimate_parameters()` actually accept are defined in the installed `non_local_detector` package, not in Spyglass. `n_chunks` and `cache_likelihood` are the canonical OOM knobs there, but if either appears to be silently ignored or rejected by your installed version, verify against the live signature:
  ```python
  import inspect, non_local_detector
  # whichever classifier class your decoding_params instantiates, e.g.:
  from non_local_detector.models import ClusterlessDecoder
  print(inspect.signature(ClusterlessDecoder.predict))
  print(inspect.signature(ClusterlessDecoder.estimate_parameters))
  ```
  Spyglass itself does no allow-list filtering of `decoding_kwargs` — it passes the dict through — so anything `predict` accepts you can put there. (Some versions of `non_local_detector` use a helper like `get_valid_kwargs` to split fit vs predict kwargs; either way the source of truth is the installed package.)

## (2) Let JAX use more of the 80 GiB

JAX/XLA pre-allocates a memory pool the first time you touch a device. The default pool is `XLA_PYTHON_CLIENT_MEM_FRACTION=0.75`, i.e. ~60 GiB on your 80 GiB card. Bumping it up gives `predict` more room before OOM:

```python
import os
os.environ["XLA_PYTHON_CLIENT_MEM_FRACTION"] = "0.95"   # ~76 GiB on 80 GiB

# import jax / spyglass.decoding AFTER setting the env var
from spyglass.decoding.v1.clusterless import ClusterlessDecodingV1
ClusterlessDecodingV1.populate(key)
```

This must be set *before* JAX initializes the GPU, so put it at the very top of the populate script (or export it in the shell before `python ...`). It's complementary to (1), not a replacement — chunking removes the peak; the fraction bump just buys you more total room.

Other JAX env vars that sometimes help in this regime:
- `XLA_PYTHON_CLIENT_PREALLOCATE=false` — disables pre-allocation entirely; allocates on demand. Safer for shared GPUs, slightly slower, and can fragment.
- `XLA_PYTHON_CLIENT_ALLOCATOR=platform` — forces the platform allocator (closer to PyTorch's caching-allocator behavior). Useful if you suspect fragmentation rather than a true peak.

I'd start with `MEM_FRACTION=0.95` + `n_chunks` and only reach for the others if those two don't clear it.

## What I'd actually do, in order

1. Add a new `DecodingParameters` row with your existing `decoding_params` plus a `decoding_kwargs={'n_chunks': 10, 'cache_likelihood': False}` sibling key. Re-point `DecodingSelection` to it.
2. Set `XLA_PYTHON_CLIENT_MEM_FRACTION=0.95` in the populate script's environment.
3. Re-run `ClusterlessDecodingV1.populate(key)`.
4. If it still OOMs, raise `n_chunks` (20, 50). The cost of more chunks is mostly marginal recompute / launch overhead, not correctness — the algorithm chunks along time, not state.
5. Only if you've pushed `n_chunks` very high and still see the issue should you suspect the *state* dimension (n_state_bins=2k is on the larger side but not unreasonable); at that point look at whether your environment discretization or state-space construction is finer than it needs to be.

## Why a bigger GPU is the wrong first move

The ask isn't "I have 100 GB of unavoidable working set"; it's "JAX is trying to materialize a single 24 GiB intermediate plus its companions on a card that has 80 GiB but won't give all 80 to one allocation." Chunking removes the peak structurally. Buying an H100 or moving to a 96 GB card would mask the problem this session and re-surface it the next time someone runs a 6M-bin session. Tune the knobs first.

## Quick sanity-check on the arithmetic

`3e6 time bins * 2e3 state bins * 4 bytes (f32) = 2.4e10 bytes ≈ 22.4 GiB` per dense `(time, state)` array. JAX's reported `25,941,544,960 bytes ≈ 24.16 GiB` is consistent with one such array plus a small overhead, which matches the "I'm allocating a single forward/backward buffer" story — exactly the thing `n_chunks` divides.
