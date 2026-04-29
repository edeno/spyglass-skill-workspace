# First reference to open

**[`common_mistakes.md`](../../skills/spyglass/references/common_mistakes.md), specifically [§2 "Too-loose restriction + `fetch1()`"](../../skills/spyglass/references/common_mistakes.md#2-too-loose-restriction--fetch1).**

## Why this one first

`DataJointError: fetch1 should only be called on one tuple, but 47 were returned` is the canonical cardinality footgun, and it's the #2 entry in the skill's "top 6 highest-frequency bugs" list in `SKILL.md`. The 47 means your restriction matched 47 rows but `fetch1()` demands exactly one — so the diagnostic and fix are mechanical, not mysterious, and `common_mistakes.md` points straight at them:

- **Diagnose**: `print(len(rel))` before `fetch1()`; if `>1`, run `rel.fetch(as_dict=True)` to see which primary-key fields you forgot to pin.
- **Fix**: add PK fields to the restriction until `len(rel) == 1`. Typical culprits are an `interval_list_name`, `*_param_name`, version field, or a merge `merge_id` you under-specified.

## Optional follow-up (only if needed)

[`datajoint_api.md`](../../skills/spyglass/references/datajoint_api.md) — for the broader `fetch` / `fetch1` / `heading` / restriction mechanics if you want the underlying DataJoint semantics rather than the Spyglass-specific footgun shape. `common_mistakes.md` §2 already cross-links to it.

I'd skip [`runtime_debugging.md`](../../skills/spyglass/references/runtime_debugging.md) for this specific traceback — it's the right home for `populate()` / `make()` failures and join-multiplicity triage, but a literal `fetch1()` cardinality error is the textbook case `common_mistakes.md` was written to catch first.
