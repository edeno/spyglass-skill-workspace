# Don't run a delete yet — I need to disambiguate first

Per Spyglass's destructive-ops policy, I will not name a single delete command for this. Two reasons:

1. **"Delete my decoding results" is genuinely ambiguous.** It could mean any of several different operations with very different blast radii.
2. **Inspect-before-destroy is mandatory.** Even after we agree on which thing to delete, the right next step is to *preview* the rows / files first, then delete on your explicit confirmation.

## Which of these do you mean?

| # | Goal | What gets removed | Affects other tables? |
|---|------|-------------------|------------------------|
| A | Drop one specific decoding run (one parameter set / one interval pair) from the DB | One row in `ClusterlessDecodingV1` *or* `SortedSpikesDecodingV1` (whichever you populated), and its `DecodingOutput` part-table entry | No — leaves all other decoding runs and all upstream data intact |
| B | Drop *all* decoding results (clusterless + sorted) for this session | Every `ClusterlessDecodingV1` / `SortedSpikesDecodingV1` row whose key includes `j1620210710_.nwb` | No — but wipes every decoding parameter set you've run on this session |
| C | Reclaim disk by removing orphaned `.nc` / `.pkl` files left behind by previous deletes | On-disk files only, not DB rows | No — only acts on already-orphaned files |
| D | "Nuke the whole session" — decoding plus everything else downstream of the NWB | Decoding + LFP + ripple + position + spike sorting + … (full cascade) | Yes — destroys everything downstream of this NWB |

D is rarely what someone means by "delete my decoding results"; I'm listing it so you can rule it out.

## What I need from you

Please tell me:

1. **Which row of A/B/C/D** — and if A, the specific `decoding_param_name`, `encoding_interval`, `decoding_interval`, and which decoder (`ClusterlessDecodingV1` or `SortedSpikesDecodingV1`) you ran.
2. **Are you the experimenter on `j1620210710_.nwb`?** `.delete()` on a `SpyglassMixin` table runs `cautious_delete`, which checks team membership against `Session.Experimenter`. If you don't share a team with the experimenter, you'll get a `PermissionError` — and the right fix is to coordinate with them, not bypass the check.

## Once you answer, the shape of the workflow will be

For **A** (one specific run — most common case), the inspect-then-delete pattern uses the merge-table classmethod form (calling `merge_delete` on a *restricted* relation silently drops the restriction and would delete every entry — Common Mistake #1):

```python
from spyglass.decoding import DecodingOutput
from non_local_detector import __version__ as non_local_detector_version

# Build the FULL selection key — partial keys can match multiple rows and
# raise "Ambiguous entry" from merge_get_part, or worse, match more rows
# than you intended.
selection_key = {
    "nwb_file_name": "j1620210710_.nwb",
    "waveform_features_group_name": "<your group>",
    "position_group_name": "<your group>",
    "decoding_param_name": f"contfrag_clusterless_{non_local_detector_version}",
    "encoding_interval": "<your interval>",
    "decoding_interval": "<your interval>",
    "estimate_decoding_params": 0,
}

# Phase 1 — Inspect (do NOT delete yet)
merge_key = DecodingOutput.merge_get_part(selection_key).fetch1("KEY")
target = DecodingOutput & merge_key
print(len(target), "merge row(s) will be deleted")
print(target.fetch(as_dict=True))
```

I'd then report what the inspect shows; you confirm; only then do I run:

```python
# Phase 4 — Execute (CLASSMETHOD form — pass the key as an argument)
DecodingOutput.merge_delete(merge_key)

# Phase 5 — clean up the orphaned .nc / .pkl files left behind
DecodingOutput().cleanup(dry_run=True)   # logs paths; review them
# DecodingOutput().cleanup(dry_run=False)  # only after confirming the log
```

For **B** (all decoding runs for this session), the safe pattern is to iterate the merge IDs from `DecodingOutput.merge_restrict({"nwb_file_name": "j1620210710_.nwb"})`, inspect each, and call `DecodingOutput.merge_delete(merge_key)` per row.

For **C** (orphan-file cleanup only — no DB rows), it's just the `DecodingOutput().cleanup(dry_run=True)` → review-logs → `dry_run=False` pattern; no merge-delete needed.

**Tell me which of A/B/C/D you want, plus the missing fields for A**, and I'll run the inspect step and report the row count + sample before any delete call.
