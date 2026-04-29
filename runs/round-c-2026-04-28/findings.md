# Eval-run findings

Cross-batch narrative for the Spyglass skill eval sweep. Workspace-level (not per-iteration) so cumulative observations survive batch turnover. Append per batch; correct in place when prior characterizations need refining.

Stats live in `BATCHES.md` (per-batch totals) and `iteration-N/benchmark.json` (per-eval). This file is the qualitative thread: what's the skill doing well, what's it not, what's surprising.

## CUMULATIVE FINAL — all 7 batches, 130 / 130 evals (100%)

| | with_skill | baseline |
| --- | --- | --- |
| Evals fully pass | 111 / 130 (85.4%) | 83 / 130 (63.8%) |
| Expectations | 989 / 1032 (95.8%) | 895 / 1032 (86.7%) |

**Headline delta: +28 evals (+21.5pp) on full-eval pass, +9.1pp on expectations.**

Tokens: 5.20M with_skill + 3.15M baseline = 8.35M total (~$200). Right on the post-Batch-3 projection.

## What's working

**Hallucination resistance is the skill's strongest surface.** The two biggest deltas in batches 1–2 are both confident-fabrication cases the baseline falls into and the skill prevents:

- **Eval 81 (`abstain-v1-naming-extrapolation`)**, ws 8/8 vs bs 3/8. Baseline confidently fabricated `SpikeSortingV1` as the v1 class name; with-skill caught the v0/v1 naming asymmetry (the actual v1 class is `SpikeSorting`, no suffix). The biggest gap of the sweep so far. Traces directly to `spikesorting_v1_pipeline.md` calling out the asymmetry.
- **Eval 130 (`key-hygiene-discovery-before-fetch`)**, ws 6/6 vs bs 0/6. Baseline answered the under-specified "fetch the LFP for my session" with a single-line bare-restriction `fetch1_dataframe()` — exactly the anti-pattern the eval targets. With-skill enumerated all four LFPSelection PK fields, used `merge_get_part`, included a cardinality assert. Traces to the round-22 / round-24 work in PR #21.

**The skill catches what it was specifically built to catch.** Each win maps to a concrete reference edit:

| Eval (with-skill win) | Skill mechanism that caught it |
| --- | --- |
| 81 — v0/v1 fabrication | `spikesorting_v1_pipeline.md` v1-vs-v0 naming-asymmetry callouts |
| 130 — discovery-first | PR #21's `lfp_pipeline.md` + `feedback_loops.md` discovery shape |
| 126 — merge-master silent no-op | `merge_methods.md` § Silent wrong-count footgun |
| 129 — custom table runtime-only | The `db_graph.py` agent-vs-user routing work in PR #25 |
| 79 — `get_pk` non-existence | `spyglassmixin_methods.md` exhaustive method list + abstention discipline |

## What the baseline does well (skill's marginal value is small)

**Schema-introspection evals (73, 74, 76, 77).** Both conditions sweep 100%. "What's the PK of `Electrode`?", "What's the PK of `FirFilterParameters`?", "What part tables does `Probe` have?" — the model has these facts from training data, plus a quick source grep gets it the rest of the way.

**General DataJoint reasoning** (most `framework-concepts` and `dependency-*` evals). Both ws and bs pass cleanly. The skill's value is in Spyglass-specific routing and footgun catching, not reteaching DataJoint.

**Implication for skill design:** `common_tables.md` doesn't need to expand its coverage of static schema facts. Time better spent on the failure modes the baseline misses.

## Failure-shape patterns in the baseline's 8 misses

5 of 8 baseline misses are precision-on-enumeration, not substantive errors. The grader rubric requires the response to name *all* relevant entities; a baseline that names "most of them but not all" fails just that check. Fair, but worth tracking whether this pattern dominates later batches — if so, "name every direct parent" rubrics may be over-strict.

The 3 substantive misses:
- Eval 81 — actual fabrication (the only outright wrong factual claim by baseline so far).
- Eval 130 — wrong shape of answer (bare restriction instead of discovery).
- Eval 126 — partial: baseline got the diagnosis right but didn't route to `merge_methods.md` (skill-only artifact, expected).

## Batch 3 update — pipeline-usage round 1

**Result: dead tie.** Both with_skill and baseline scored 20/20 evals fully pass, 194/194 expectations (100%) on substring AND behavioral checks. Zero delta.

**Why the delta compressed.** Batch 3's evals were pipeline-usage / atomic / join / disambiguation / counterfactual / workflow-position / dependency-tracing — categories where the failure modes aren't the hallucination ones the recent reference / validator / eval rounds targeted. The grader's note: "with_skill's measurable advantages over baseline (source-line citations, v0/v1 precision, footgun anchoring to stable identifiers) live below the binary-pass-fail level — the rubric did not capture them."

**This confirms the Batch 1–2 hypothesis.** The skill's value concentrates in:

- **Hallucination prevention** (Batches 1, 2): +6.4–7.5pp delta. Real wins.
- **Workflow guidance** (Batch 3): no measurable delta at the pass/fail level. Qualitative wins (better citations, more precise v0/v1 calls) don't show up in the rubric.

**Implication for skill design.** Time spent expanding `common_tables.md` / `datajoint_api.md` schema-fact coverage is mostly wasted; the model already knows that surface. Time spent on hallucination-shaped scenarios (key invention, blob-vs-heading confusion, v0/v1 cross-version copying, merge-master silent no-ops) is where the +6pp came from. Continue investing there.

**Operational note: token rate limit hit mid-batch.** 7 of 40 dispatches hit "You've hit your limit · resets at 10:30am" and had to be retried after the rate limit reset. Batches 4–7 will need similar contingency handling; batch sizes of ~40 parallel subagents are right at the edge of what the harness will allow without rate-limiting partway. No technical fix beyond "wait and retry."

## Batch 6 update — runtime-debugging cluster

**Result: ws 19/19 (100%) vs bs 18/19 (94.7%), +5.3pp on full-eval pass; ws 120/120 vs bs 117/120 (97.5%), +2.5pp on expectations.** The single baseline miss is eval-082, which asks "which reference file inside the spyglass skill should I open after a `populate_all_common` failure" — by construction the baseline cannot satisfy a question whose answer *is* a skill-only filename, so this delta is mechanical rather than substantive. On the 18 non-routing evals, both conditions matched on every diagnosis, every fix shape, and every "don't do X" warning.

**This refutes the pre-batch hypothesis.** I expected runtime-debugging to favor the skill via the structured failure-signature index (`runtime_debugging.md`, `populate_all_common_debugging.md`). The actual finding: baseline already produces correct individual diagnoses for well-known runtime symptoms (cardinality errors, OOM, FK-ancestor missing, populate-non-pk-dict, dependent-attribute joins). The skill's incremental value sits at literal routing ("read this filename") and below the binary-pass-fail level — better source citations, footgun anchoring to stable identifiers, more confident v0/v1 carveouts.

**Implication for skill design.** Two of the four batches measured (3 and 6) show ≤+2.5pp delta. The skill's high-signal surface is concentrated in:

- **Adversarial hallucination prevention** (Batch 2): +5.6pp from confident-fabrication catches.
- **Key hygiene + merge gotchas** (Batch 1): +7.5pp from discovery-first / silent-no-op / cross-version traps.

Time spent expanding `runtime_debugging.md` / `populate_all_common_debugging.md` is now demonstrably lower-yield than time spent on hallucination-shaped scenarios. The current references probably already capture the practically reachable runtime-debugging headroom.

**Operational note.** Batch 6 ran 38 dispatches without hitting the token rate limit, unlike Batch 3 (7 retries). Plausible difference: Batch 6 was dispatched in early afternoon vs. Batch 3 mid-morning.

## Batch 5 update — parameter-understanding + counterfactual cluster

**Result: ws 6/8 (75%) vs bs 5/8 (62.5%) on full-eval pass; 54/57 vs 49/57 on expectations (94.7% vs 86.0%, +8.7pp).** Behavioral checks alone: ws 29/32 vs bs 28/32 (+1). Substring-level signal was unusually strong: ws missed 7 literal substrings vs bs missed 14 — but a behavioral grader pass flagged ~7 of these as over-strict literal phrasing (synonyms used by both conditions); those were relaxed in `evals.json` and the responses re-graded.

**Two real skill wins in this batch:**

- **eval-061 (`SortGroup.set_group_by_electrode_group` on multi-shank probes).** Skill caught two technical facts baseline missed: (1) the method is **v0-only** (the v1 `SortGroup` only exposes `set_group_by_shank`); (2) the SpikeInterface `populate` rejection — bundling shanks produces duplicate `(x, y)` contact positions that fail validation as "contact positions are not unique". Baseline gave a reasonable geometry-based explanation but missed both the version asymmetry and the actual error message.
- **eval-116 (counterfactual ripple z-threshold change).** Skill correctly noted that `RippleTimesV1` is the *terminal* output of the ripple pipeline (no Spyglass-managed downstream tables) and framed the issue as provenance corruption with explicit reference to `ripple_param_dict`. Baseline suggested re-creating `RippleLFPSelection`, which is a factual error.

**One outlier going the other way: eval-118 ws 2/4 behavioral vs bs 4/4.** The skill response got distracted by source-skepticism — spent a section verifying whether `position_bin_size` literally exists as a kwarg in the `non_local_detector` API and consequently never named the qualitative cascade direction or the specific upstream Group tables. The baseline answered the substantive question more directly. This is a generation-time choice (skill response *over-applied* the verify-before-claim discipline), not a skill content gap — but it's the first ws-worse-than-bs case in the sweep and worth tracking. Hypothesis: the skill's source-grounding directives can occasionally tip into source-checking instead of answering.

**Implication for skill design.** Two new signals:

1. The skill's value on parameter understanding is concentrated where the answer requires version-aware Spyglass internals (v0/v1 method names, exact error strings, exact param-blob structure). On smoother param questions where the model already has solid intuition, both conditions converge.
2. The eval-118 outlier suggests the verify-before-claim Core Directive may be slightly over-applied in some prompts. Worth watching in Batch 4 (pipeline-usage round 2): does ws ever *under-answer* by getting stuck in caveat mode?

**Operational note.** Batch 5 again ran 16 dispatches without rate limiting, but two stalled (eval-117 bs and eval-118 ws — both took >450s, eval-118 ws timed out and was retried). Batches with longer prompts that pull in multiple references seem more prone to stalls.

## Batch 7 update — setup / ingestion / pipeline-authoring / destructive / table-classification / non-activation cluster

**Result: ws 22/30 (73.3%) vs bs 5/30 (16.7%) on full-eval pass; ws 214/237 vs bs 161/237 on expectations (90.3% vs 67.9%, +22.4pp). Behavioral checks alone: ws 104/113 (92.0%) vs bs 74/113 (65.5%), +26.5pp — by far the largest behavioral spread of the sweep.**

**This is where the skill earns its keep most decisively.** The setup-troubleshooting + ingestion + pipeline-authoring sub-clusters are the parts of Spyglass with the most lab-specific mechanism — three-layer permission triage, channel-slice diagnostic via `nwb.electrodes.colnames`, conda+pip env collisions, the `SortedSpikesGroup.create_group` helper, the `AnalysisNwbfile.build()` context manager pattern. The model has weak training-data coverage of these and consistently lands on plausible-but-wrong diagnoses without the skill.

**The cleanest blowouts:**

- **Eval-107 (compound sorted-spikes across sort-groups): ws 5/0 vs bs 0/0.** Baseline never reached for `SortedSpikesGroup` / `create_group` / `UnitSelectionParams` and instead built a per-sort-group aggregation table from `CuratedSpikeSorting` directly — wrong abstraction layer. Skill correctly routed to the existing group-table pattern.
- **Eval-045 (config-permission-triage): ws 5/1.** The skill correctly distinguished three different "permission denied" failures (MySQL grants vs filesystem perms vs `LabMember.LabMemberInfo` for `cautious_delete`). Baseline collapsed all three into "MySQL grants."
- **Eval-032 (channel slice parents): ws 4/1.** Baseline gave plausible electrode-mismatch theories; skill landed on the canonical Spyglass-source-grounded diagnosis (`nwb.electrodes.colnames` reveals `channel_name` vs `electrode_id` mismatch).
- **Eval-040 (cross-machine config stores): ws 5/3.** Baseline correctly identified per-machine `dj.config['stores']` paths; skill added the SpyglassConfig precedence ladder + `save_dj_config` regeneration recipe.

**One outlier going the other way: eval-041 (config-key-error-after-pull): ws 1/5 vs bs 3/5.** The skill response opens "probably not in-DB schema drift" and demotes schema drift to the third-priority hypothesis (preferring stale params blobs / half-upgraded install). It then explicitly recommends `git checkout <yesterday's-sha>` as a fix — exactly what behavioral check #5 forbids. Baseline diagnosed code-ahead-of-DB correctly and pointed at `CHANGELOG.md` (also lost #5 to its own `git checkout` recommendation). **This is the second consecutive batch with a ws-worse-than-bs outlier driven by the skill response over-applying source-skepticism / verify-before-claim discipline** — eval-118 in Batch 5 had the same shape. Both cases the skill response was right to be cautious, but cautioned its way into not answering the question. Worth flagging as a skill-design refinement target: the verify-before-claim Core Directive may benefit from a "but state the most likely answer first" clarification.

**Adversarial pushback is now baseline-strong.** Evals 022, 023, 024 (password-exposure, skip-dry-run, skip-cautious-delete) all tied at 3/3. The model has internalized the "push back when asked to skip safety steps" behavior independent of the skill. The skill's marginal value on these is now down to specific recommended commands (`scrub_dj_config.py`, `force_permission=True`).

**Operational note.** 15 of 60 dispatches hit the token rate limit at 3:30pm ET mid-batch — the reset-time pattern from Batch 3 returned. All 15 were retried successfully. Batch 7 + Batch 4 (the remaining 19-eval pipeline-usage round 2) together would push the cumulative token count to ~8.5M, in line with the post-Batch-5 estimate.

**Cumulative implication for skill design.** The skill's value distribution is now clear:

- **Highest signal**: setup/ingestion/pipeline-authoring (+22-26pp) and adversarial-hallucination (+5-8pp). Time spent here pays back.
- **Lowest signal**: pipeline-usage / atomic-read / table-classification / runtime-debugging (≤+2.5pp). Baseline is already strong; further investment is low-yield.
- **Watch closely**: source-skepticism over-application is a real failure mode (eval-118, eval-041). Worth scoping a Round-D edit to clarify when to verify vs when to answer.

## Batch 4 update — pipeline-usage round 2 (final batch)

**Result: ws 10/19 (52.6%) vs bs 7/19 (36.8%) on full-eval pass; ws 158/175 vs bs 141/175 on expectations (90.3% vs 80.6%, +9.7pp). Behavioral checks alone: ws 54/63 (85.7%) vs bs 44/63 (69.8%), +15.9pp.**

Sub-clusters where the skill helped most:

- **Joins / atomic-read** (eval-095 join-dependent-attr-refusal +2, eval-094 target-sampling-rate +2). The skill consistently routed responses through the right part-table or exact-match keying rule and flagged silent-no-op restriction footguns.
- **Session introspection** (eval-102 session-recording-devices +2). Skill correctly named `Session.DataAcquisitionDevice` part table; baseline conflated with top-level `Session`.

Sub-clusters where both tied:

- **Table-usage easies** (eval-090, 091, 092, 093 — "what's next after row X"). Pipeline-position questions where the model has solid intuition. Same shape as Batch 3.

Substantive misses by both:

- **Eval-072** (LFPBandV1 dependency walk): neither response named `Raw` — the static FK graph doesn't surface the runtime fetch in `LFPV1.make()`.
- **Eval-100** (post-curation clusterless workflow): with_skill assumes curation is required; baseline says optional — both wrong on the actual constraint.
- **Eval-108** (sorted-spikes hippocampal): neither walked `SortGroup.SortGroupElectrode * Electrode * BrainRegion` to derive hippocampal sort_group_ids automatically.

**No ws-worse-than-bs outliers in this batch** — the eval-118 / eval-041 over-source-skepticism failure mode did not fire here. With_skill responses for 102/104/105 declined to invent specific values but cleanly named the canonical query path, which is the right shape.

**One forbidden-substring relaxation applied:** eval-102's `Session.fetch1("device")` forbidden was firing on the skill's own guardrail-mention ("Don't write `Session.fetch1("device")`..."). Removed; behavioral check covers the intent.

## Final summary — what the sweep proved

The skill's value distribution across all 7 batches:

| Cluster | Batch | Eval delta | Behavioral delta | Notes |
| --- | --- | --- | --- | --- |
| Setup / ingestion / pipeline-authoring / adversarial | 7 | +17 evals | **+26.5pp** | Largest spread — Spyglass-specific mechanism, weak training coverage |
| Key hygiene + merge gotchas | 1 | +3 evals | +7.5pp | Confident-fabrication catches |
| Hallucination resistance + framework | 2 | +3 evals | +5.6pp | v0/v1 cross-version naming, abstention discipline |
| Pipeline-usage round 2 | 4 | +3 evals | +15.9pp | Joins / atomic-read / session-introspection |
| Param + counterfactual | 5 | +1 eval | +3.1pp (29/32 vs 28/32) | One ws-worse outlier (eval-118 over-skepticism) |
| Runtime debugging | 6 | +1 eval | +2.2pp | Skill wins on routing only; baseline strong on individual diagnoses |
| Pipeline-usage round 1 | 3 | 0 evals | 0pp | Tie — atomic-read is baseline-strong territory |

**Two clear failure modes for the skill identified:**

1. **eval-118** (Batch 5) and **eval-041** (Batch 7): skill response over-applies verify-before-claim discipline, getting stuck in source-skepticism instead of naming the most likely answer first. Worth a Round-D edit to clarify "state most-likely-answer first, then verify."

2. **No clean failure mode for skill content** beyond those two — the skill's references reliably caught the failure modes they were specifically built to catch (eval-81 v0/v1 fabrication, eval-130 discovery-first, eval-126 silent no-op, eval-129 custom table runtime, eval-79 get_pk non-existence, eval-061 multi-shank v0/v1, eval-107 SortedSpikesGroup routing, eval-032 channel_name diagnostic, eval-045 three-layer permission triage).

**Implication for skill design.** Continue investing in the high-signal surfaces:

- Setup-troubleshooting (Batch 7's biggest wins live here)
- Hallucination prevention (Batch 1, 2 — confident-fabrication catches)
- Lab-specific helpers + APIs (`SortedSpikesGroup.create_group`, `AnalysisNwbfile.build()`, `scrub_dj_config.py`, `verify_spyglass_env.py`)

De-prioritize:

- Schema-fact recall (Batch 3 — model already has these from training)
- Generic DataJoint reasoning (Batch 3, parts of Batch 4)
- Individual runtime diagnoses (Batch 6 — model has the symptoms in training)

## Open hypotheses for later batches

- **Batch 3 (pipeline-usage round 1, 20 evals).** Longer prompts with multi-step reasoning. Failure modes likely structural (wrong sequence of populate steps, missed prerequisites) not factual. Hypothesis: the skill's marginal value should be *larger* here than in the schema-introspection cluster.
- **Batch 6 (runtime-debugging, 19 evals).** Failure shape is "give the wrong diagnosis." The skill provides a structured failure-signature index (`runtime_debugging.md`); does the baseline match that structure or wander? Hypothesis: skill wins by routing, baseline wins on individual diagnoses where the symptom is well-known.
- **Will the +5–7pp delta scale or compress?** Batches 1–2 averaged +6.5pp. If pipeline-usage shows a wider gap, that argues for further investment in those references. If it compresses, the skill is already doing most of its work and Batch C/D follow-ups (validator hardening, more evals) would be lower priority.

## Corrections log

- **2026-04-28 — Eval 80 baseline characterization.** Initial Batch 2 summary called eval 80's baseline miss a "routing miss" (didn't cite `destructive_operations.md`). Corrected: baseline did mention `destructive_operations.md`. The actual miss was narrower — baseline named only two of the three direct parents (`RippleLFPSelection`, `RippleParameters`) and left out `PositionOutput`. Failure shape: precision on enumeration completeness, not routing. Severity ranking among Batch 2 misses: 81 (real fabrication) ≫ 79 (incomplete abstention) > 80 (narrow precision miss).
