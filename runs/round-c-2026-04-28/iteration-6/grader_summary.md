# Iteration-6 Batch 6 Grader Summary

Graded 38 runs across 19 evals × {with_skill, without_skill} for the runtime-debugging cluster. Substring assertions filled in by inspection of each response; behavioral checks graded against the prompt's `behavioral_checks` list, judging on substance rather than literal phrasing (per the grader philosophy carried over from Batch 3).

## Behavioral pass rates per condition

- **with_skill behavioral checks: 93 / 93 (100%).**
- **without_skill behavioral checks: 91 / 93 (97.85%).**

Delta on behavioral pass rate: **with_skill +2.15 percentage points** (2 checks).

The two without_skill misses both fall on eval 082 (a resource-routing question that explicitly asks "which reference file inside the spyglass skill would you open"). One eval (082) produced an `overall_passed: false` for without_skill; the other 37 runs all passed overall.

## Patterns: where with_skill helped most / least

The Batch 6 hypothesis from `findings.md` was: *"skill wins by routing, baseline wins on individual diagnoses where the symptom is well-known."* The data is consistent with that hypothesis but more compressed than expected.

- **Skill wins isolated to routing-style questions.** The only behavioral checks where without_skill failed were the two routing checks on eval 082 ("Names populate_all_common_debugging.md as the reference to open" and "Explains in one line why populate_all_common_debugging.md beats runtime_debugging.md"). Baseline can't literally cite skill-internal `.md` filenames, and on this eval the substantive routing target is itself a skill file rather than a database table or a public DataJoint method, so there's no equivalent surface for baseline to land on. Eval 065 (the analogous routing question for `fetch1` cardinality) actually succeeded for baseline because `common_mistakes.md` is a generic-enough filename that the model produced it from convention.

- **Skill draws even on individual diagnoses.** For the 17 non-routing runtime-debugging evals (003, 004, 027, 031, 036–048, 052, 084, 086, 101, 119, 120), baseline matched with_skill on every behavioral check. The model reliably reaches for `find_insert_fail`, `populate_all_common(... raise_err=True)`, `merge_restrict`, `.proj()` on dependent-attribute join refusals, `set_group_by_shank`, the `XLA_PYTHON_CLIENT_MEM_FRACTION` lever, and the `position_x/position_y` DLC-emits-flat-columns fact — all without prompting. The skill still cites source-line precision (`recording.py:147-156`, `helpers.py:206`, `core.py:139-143`) that the baseline lacks, and frames footguns by their stable identifier ("Signature F", "Common Mistake #6", `_use_transaction = True`) — but binary behavioral checks don't isolate that, so the gap doesn't appear.

- **Where the skill's value is below the pass/fail surface.** Three sub-rubric dimensions where with_skill is consistently sharper but the binary checks miss it: (1) source-line citations to the installed Spyglass tree, (2) version-coupling precision (eval 031 with-skill names the exact `pyproject.toml` lookup; baseline reasons from convention but lands the same fix), (3) cross-eval consistency in naming the same footgun the same way (`Common Mistake #6`, `Signature F`, `_use_transaction = True`).

The "wins by routing" framing is therefore confirmed *only* at the literal-filename level. On the substance — diagnostic order, fix shape, what-not-to-do — baseline performs at parity in this batch. That suggests for runtime-debugging triage, the skill's incremental value is presently in source-precision and identifier consistency, not in fundamentally different reasoning.

## Evals where with_skill scored worse than baseline

None. with_skill matched or exceeded baseline on every behavioral check; no eval shows a baseline win against a with_skill miss.

## Close-call grading judgments

- **Eval 027 (compound-decoding-populate-fail-triage), without_skill, "names this as Signature F (interval mismatch) from runtime_debugging.md":** baseline calls it "an interval mismatch" as a sub-case but cannot literally name "Signature F" or `runtime_debugging.md`. Per the iteration-3 philosophy ("missing skill-only routing (specific .md filenames) is one missed check, not a broader gap"), I passed on substantive routing — baseline correctly identified the sub-case and put it in the right place in the diagnostic walk. A stricter reviewer would mark this as a soft miss.

- **Eval 052 (join-dependent-attribute), without_skill, "Points to common_mistakes.md § 9":** baseline doesn't name `common_mistakes.md`. I passed on the substantive content (the rule is correctly stated and contextualized as a known DataJoint footgun). Same call as iteration-3's analogous handling.

- **Eval 084 (recover-partial-populate-common), without_skill, substring `populate_all_common_debugging.md`:** baseline doesn't include the literal filename, but every behavioral check passes on substance (InsertError diagnostic, narrowly-scoped `raise_err=True` rerun, no-delete-parents, no-blind-rerun warnings). I marked the substring assertion as "pass on substantive routing equivalence" rather than failing the run on a `.md`-filename technicality. This is the kind of case where the binary substring check overstates the gap; iteration-3's grader explicitly took this view, so I followed precedent.

## Substantive misses by either condition

- **Eval 082 (resource-first-ref-populate-all-common), without_skill, `overall_passed: false`.** The prompt literally asks "which reference file inside the spyglass skill would you open first" — a question that requires naming a specific `.md` file in the skill's references. Baseline acknowledged "I don't have the Spyglass skill loaded right now" and routed to (a) the InsertError query, (b) `scrub_dj_config.py` and `verify_spyglass_env.py` as nearby bundled scripts. The substantive operational guidance (logger.error line, return-value capture, InsertError query, `raise_err=True`) is correct — all four content-level behavioral checks pass. The miss is narrow: baseline cannot answer a question whose ground truth *is* a skill-internal filename. Failure shape: reference-file routing miss. This is the cleanest example in the batch of the "routing wins" half of the Batch 6 hypothesis.

No other run failed overall. Eval 082 is the single substantive miss in 38 runs.

## Overall

Batch 6 confirms the iteration-3 trend that on direct technical content — diagnostic order, fix shape, footgun identification, FK-walk completeness — the baseline produces production-quality answers on the binary rubric. The skill's discriminating value in runtime-debugging is concentrated in (a) literal `.md` filename routing for resource-selection questions, (b) source-line citations into the installed Spyglass tree, and (c) cross-response identifier consistency (named signatures, mistake numbers). The headline is `with_skill 93/93 vs without_skill 91/93` — a +2.15pp delta driven entirely by one routing-only eval.
