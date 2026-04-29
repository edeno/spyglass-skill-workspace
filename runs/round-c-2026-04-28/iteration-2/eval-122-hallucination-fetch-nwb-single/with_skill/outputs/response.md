# `fetch_nwb1()` — no such method exists

Spyglass does not have a `fetch_nwb1()` shorthand. The only NWB-fetch helper on `SpyglassMixin` tables is `fetch_nwb`, defined at `src/spyglass/utils/mixins/fetch.py:284`. Its docstring states the return type explicitly:

```
Returns
-------
nwb_objects : list
    List of dicts containing fetch results and NWB objects.
```

So `fetch_nwb()` always returns a **list of NWB** result dicts — even when the restriction matches a single row, you get a list of one. There is no analog to `fetch1()` (which raises if cardinality != 1) for the NWB path. A grep across the entire `src/spyglass/` tree confirms `fetch_nwb1` does not appear anywhere.

## Verify with introspection (don't take my word for it)

```python
from spyglass.lfp.v1.lfp import LFPV1
import inspect

[m for m in dir(LFPV1) if "fetch" in m]
# fetch_nwb is there; fetch_nwb1 is not.

inspect.getsource(LFPV1.fetch_nwb)  # see the real signature + docstring
hasattr(LFPV1, "fetch_nwb1")        # False
```

`dir()` and `inspect.getsource` are the right primitives any time you suspect a method might be a name you half-remember — they read what's actually on the class instead of inviting a hallucinated signature.

## The correct single-row idiom

The `[0]` you keep typing is correct. The trick is to make sure the restriction is genuinely unique *first*, so the list is guaranteed to be length 1:

```python
# (a) Resolve to a unique primary key with fetch1('KEY') — raises if not unique:
key = (LFPV1 & {
    "nwb_file_name": "j1620210710_.nwb",
    "lfp_electrode_group_name": "CA1",
    "target_interval_list_name": "02_r1",
    # ... add PK fields until len((LFPV1 & restr)) == 1
}).fetch1("KEY")

nwb = (LFPV1 & key).fetch_nwb()[0]   # list-of-one, [0] is safe

# (b) Or assert before indexing if you're building this inline:
rel = LFPV1 & key
assert len(rel) == 1, f"expected 1 row, got {len(rel)}"
nwb = rel.fetch_nwb()[0]
```

## Why a `fetch_nwb1()` would be a footgun anyway

When you find yourself wishing for `fetch_nwb1()`, the underlying problem is almost always that **the restriction isn't actually unique** — multiple rows survive `&`, `fetch_nwb()` returns a list-of-N, and `[0]` silently picks an arbitrary one. A hypothetical `fetch_nwb1()` that raised on cardinality > 1 would help, but the real fix is upstream: tighten the restriction (use `fetch1('KEY')` first to confirm uniqueness, or print `len(rel)` and inspect with `rel.fetch(as_dict=True)` to find the missing PK field). This is Common Mistake #4 in the skill — `fetch_nwb()` silently returning multi-row results, unlike `fetch1()`. Fix the restriction, not the fetch helper.

For the full method registry on mixin tables (including `fetch_nwb`, `fetch_pynapple`, `cautious_delete`, `<<`/`>>`, etc.), see `references/spyglassmixin_methods.md`.
