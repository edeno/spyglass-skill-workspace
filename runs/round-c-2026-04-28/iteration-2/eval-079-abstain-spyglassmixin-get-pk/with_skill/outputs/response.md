# `SpyglassMixin.get_pk()` doesn't exist — use `.fetch('KEY')`

Short answer: there is **no `get_pk()` method on `SpyglassMixin`**. I'm not going to fabricate a signature for it. Memory of "I think there's a convenience" is the exact failure mode the skill's "Do not invent identifiers" core directive guards against — so let's verify, then use the real idiom.

## Verification (so you can repeat it)

Two independent primitives, either is sufficient:

1. **Source grep** — the mixin lives at `src/spyglass/utils/dj_mixin.py` (with helper modules under `src/spyglass/utils/mixins/`). A grep across the whole package returns no hits:

   ```bash
   grep -rn "get_pk" src/spyglass/
   # (no output — no def get_pk anywhere in Spyglass)
   ```

2. **Runtime introspection** — in a Python session against your real install:

   ```python
   from spyglass.utils import SpyglassMixin
   [m for m in dir(SpyglassMixin) if "pk" in m.lower()]
   # -> ['dict_to_pk']   # the only PK-flavored helper; takes a dict, not a query
   ```

   `dict_to_pk(key)` projects an over-specified dict down to just the PK fields — it doesn't fetch rows. It's not what you want here.

## What you actually want: PK dicts for every row in a restriction

DataJoint already gives you this directly; no Spyglass-specific helper is needed.

```python
# Option 1 (canonical): list of primary-key dicts, one per row
pk_dicts = (Table & restriction).fetch('KEY')
# -> [{'nwb_file_name': '...', 'interval_list_name': '...'}, ...]

# Option 2 (equivalent, more explicit): project to PK then fetch as dicts
pk_dicts = (Table & restriction).proj().fetch(as_dict=True)
```

`'KEY'` is a DataJoint sentinel that tells `fetch` "give me only the primary-key columns, as a list of dicts." This is the idiom Spyglass itself uses everywhere it needs to iterate keys (e.g. for `populate()`, `merge_get_part`, cascade walks) — see `references/datajoint_api.md:106` and `:127` in the skill, which list `.fetch('KEY')` as the standard "primary-key dicts only" form.

A few practical notes:

- Both forms return a **list** even for a single row. If you need exactly one PK dict, use `.fetch1('KEY')` — but verify cardinality first (`print(len((Table & restriction)))`); `fetch1` raises if `len != 1`.
- `Table.primary_key` (a class attribute, list of field names) is the right thing if you only want the PK *schema*, not row values.
- For the supported helper surface on the mixin (what *does* exist: `fetch_nwb`, `cautious_delete`, `restrict_by`, `dict_to_pk`, `dict_to_full_key`, `file_like`, `restrict_by_list`, `find_insert_fail`, `get_fully_defined_key`, `ensure_single_entry`, `get_params_blob_from_key`, etc.), see `skills/spyglass/references/spyglassmixin_methods.md`.

## Confidence

- **Confirmed**: `get_pk` is not defined on `SpyglassMixin` or anywhere in `src/spyglass/` (grep, today's source).
- **Confirmed**: `(Table & restriction).fetch('KEY')` is the documented DataJoint idiom for "PK dicts for every row in this restriction" and is the form used throughout Spyglass.
- **Unknown / not invented**: any specific signature, return shape, or kwargs for `get_pk()` — there's nothing to report because the method doesn't exist. If you saw it in a notebook or docstring somewhere, paste the snippet and I'll trace where that name actually came from (most likely a custom subclass, an old branch, or a misremembered `dict_to_pk` / `fetch('KEY')`).
