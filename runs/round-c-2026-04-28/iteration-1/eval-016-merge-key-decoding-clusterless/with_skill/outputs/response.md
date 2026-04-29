# Finding the `DecodingOutput` `merge_id` for that clusterless run

Two phases: **(1) discover** the actual `decoding_param_name` registered in your DB (it's lab-specific — don't guess), then **(2) restrict** the merge table.

A note on shape before code: `DecodingParameters` is a single `dj.Lookup` table that holds **both** clusterless and sorted-spikes parameter sets. There is no separate "clusterless decoding parameters" table — the only thing distinguishing the two is the param name, by convention something like `*_clusterless_*` vs `*_sorted_*` (stock defaults are `contfrag_clusterless_<version>`, `nonlocal_clusterless_<version>`, `contfrag_sorted_<version>`, `nonlocal_sorted_<version>`, but a lab can register anything). So the param name has to come out of the table, not out of my head.

## Phase 1 — Discover the clusterless param name

```python
from spyglass.decoding import DecodingParameters

# All registered param sets:
DecodingParameters.fetch("decoding_param_name")

# Or filter to just the clusterless ones by naming convention:
clusterless_names = (
    DecodingParameters
    & 'decoding_param_name LIKE "%clusterless%"'
).fetch("decoding_param_name")
print(clusterless_names)
```

Pick the one that matches what you actually ran (e.g. `contfrag_clusterless_<non_local_detector_version>` if you used the stock continuous-fragmented default, or whatever custom name your lab inserted). Assign it:

```python
decoding_param_name = "<the name you saw above>"
```

If you genuinely don't know which one was used for this populate, also run:

```python
from spyglass.decoding.v1.clusterless import ClusterlessDecodingV1

(ClusterlessDecodingV1
 & {"nwb_file_name": "j1620210710_",
    "encoding_interval": "02_r1",
    "decoding_interval": "02_r1"}
).fetch("decoding_param_name", "waveform_features_group_name", "position_group_name")
```

That tells you which `decoding_param_name` (and which `waveform_features_group_name` / `position_group_name`) actually has a populated row for this session and these intervals — those are the remaining PK fields you need to make the restriction unique.

## Phase 2 — Restrict `DecodingOutput` and fetch the merge_id

`DecodingOutput` is a merge master with `merge_id` (UUID) as its only PK. Use `merge_get_part` (not `&` — restricting a merge master with non-PK fields silently returns the whole table, see Common Mistake #6 in the skill).

```python
from spyglass.decoding import DecodingOutput

selection_key = {
    "nwb_file_name": "j1620210710_",
    "waveform_features_group_name": features_group_name,   # from Phase 1 query
    "position_group_name":          position_group_name,   # from Phase 1 query
    "decoding_param_name":          decoding_param_name,   # from Phase 1 query
    "encoding_interval": "02_r1",
    "decoding_interval": "02_r1",
    # estimate_decoding_params: include if you populated more than one variant
}

merge_id = DecodingOutput.merge_get_part(selection_key).fetch1("KEY")["merge_id"]
print(merge_id)
```

`merge_get_part` dispatches through `merge_restrict_class` internally, so the key must resolve to **exactly one** parent-table (`ClusterlessDecodingV1`) row. A partial key like `{"nwb_file_name": ...}` alone usually doesn't — you'll get `ValueError: Ambiguous entry`. The full selection key above is the safe shape.

## Phase 3 — Fallback if `merge_get_part` returns nothing

If the chosen `decoding_param_name` doesn't match any populated row (typo, wrong variant, never populated), `merge_get_part` will fail. Inspect the candidates directly via the part table on the merge master:

```python
candidates = (
    DecodingOutput.ClusterlessDecodingV1
    & {"nwb_file_name": "j1620210710_",
       "encoding_interval": "02_r1",
       "decoding_interval": "02_r1"}
)
candidates.fetch(as_dict=True)   # rows you can pick from by eye
# Then, once you've identified the row you meant:
merge_id = candidates.fetch1("merge_id")   # or .fetch("merge_id") if multiple
```

Each row already carries its `merge_id`, so you can grab it straight from the part table — no need to round-trip through `merge_get_part`.

## Why the discovery step is non-negotiable

`decoding_param_name` is a free-form `varchar(80)` lookup key whose contents are whatever your lab inserted (often via `DecodingParameters().insert_default()` for the stock presets, but custom names are common). I don't know what's in your `DecodingParameters` table without looking — so guessing a name like `"default_clusterless"` would just be making something up. The two queries above (`DecodingParameters.fetch(...)` and the `ClusterlessDecodingV1` restriction) take a second and remove the guesswork.
