# Iteration-2 Batch 2 Grader Summary

## Behavioral check pass rates (20 evals × 2 conditions)

- **with_skill**: 66/66 behavioral checks pass (100%)
- **without_skill**: 61/66 behavioral checks pass (~92%)

The five baseline failures are concentrated in two evals: eval-079 (1 fail, "States that get_pk does not exist") and eval-081 (4 fails — every behavioral check missed).

## Patterns observed

- **Hallucination resistance is the cleanest separator.** On eval-081 (`abstain-v1-naming-extrapolation`) the with_skill response correctly identifies that `SpikeSortingV1` does not exist and routes to `SpikeSorting` (no V1 suffix), naming the v0→v1 asymmetry explicitly. The baseline confidently imports `SpikeSortingV1` and recommends calling `.populate()` on it — a complete fabrication. This is the single most consequential gap in the batch: the baseline writes runnable-looking code against a class that will fail at import time.
- **Routing-to-skill-references checks** are reliably hit only in with_skill, as expected (e.g. `spyglassmixin_methods.md` substring missing from baseline in eval-079, `spikesorting_v1_pipeline.md` missing in eval-081's baseline). These are graded as substring assertions, not behavioral checks, so they don't penalize the baseline behavioral score directly — but they're the obvious mechanism by which the skill outperforms.
- **For substantive technical pushback (eval-005, 007, 025, 030, 080, 096, 097, 109, 115, 122, 123)** both conditions perform comparably well. Both responses push back on the `.fetch()[0]` shortcut, both warn off the 200-row delete, both name `descendants()` over `children()`, and both correctly explain merge tables vs. group tables. The baseline is weaker only at the precise edges (e.g. naming `PositionOutput` explicitly in eval-080) but the broad behavioral checks pass.
- **No with_skill response scored materially worse than baseline** on any eval in this batch. The opposite-direction failure mode flagged in the grading principles did not occur here.

## Close calls / judgment notes

- **eval-079 (without_skill), check "States that get_pk does not exist"**: Marked **fail**. The baseline says "I can't confirm that SpyglassMixin has a .get_pk() method, and I'm not going to invent a signature for one" — a careful epistemic abstain that punts the question to the user's `dir()` check. With_skill, by contrast, runs the grep itself and asserts non-existence. I graded the baseline as failing this specific check because the assertion bar is "states that ... does not exist", not "abstains on whether ... exists" — the baseline never actually commits to the negative, even though the rest of its answer is reasonable. A reviewer might accept the abstain as effectively satisfying the check.
- **eval-080 (without_skill), check "Names at least two of the three actual direct parents"**: Marked **pass**. The baseline names `RippleLFPSelection` and `RippleParameters` directly and refers to "a position table" without naming `PositionOutput` — the substring assertion for `PositionOutput` is correctly graded false, but the behavioral check requires only 2 of 3, so this passes on the merits.
- **eval-080 (without_skill), check "Routes to destructive_operations.md"**: Marked **pass**. The baseline mentions `destructive_operations.md` only in a hedge ("If you have skill-side guidance on destructive deletes (something like a destructive_operations.md reference), follow that workflow"). I gave it credit because the file is named, but a stricter reviewer could mark this as fail since the baseline isn't actually routing to a file it knows exists — it's hedging that such a file might exist.

## Schema-* short-form evals (073, 074, 076, 077)

Both conditions answered concisely and correctly. Eval-074 and 076 ask for one-line answers and both responses give exactly that. Eval-073 and 077 ask for "the one-liner you'd run to verify, and list the field names" — both responses include `Electrode.primary_key` / `Probe.parts()` as required and include exactly the right field set. I treated the verification-primitive checks generously per the instructions: the bar is whether the response demonstrates the verification primitive, which both conditions clear.

## Bottom line

The skill's measurable lift in this batch is concentrated in adversarial hallucination cases where parametric memory is unreliable (most starkly eval-081, less starkly eval-079). On routine framework-concept and dependency-tracing questions, the underlying model's understanding is already strong enough that the skill mostly helps with substring-level routing and source-reference precision — the behavioral-check delta is small there, and the substring-level delta is what's doing the visible work.
