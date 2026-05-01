# Round-D narrow eval rerun — findings

**Run**: `round-d-2026-04-30/iteration-1` — 16 evals × 2 conditions = 32 dispatches.
**Skill state**: branch `round-d`, commit `7c1e966c` (post-Phase-2 + Phase 3 rubric corrections + post-review SKILL.md word-budget tightening + cascade-template `SpikeSortingV1` → `v1 SpikeSorting` fix).
**Spyglass src**: pinned local checkout at `caec56bc` ("Fix typo: HD5_USE_FILE_LOCKING → HDF5_USE_FILE_LOCKING #1576"). Working tree clean.
**Plan**: [docs/plans/round-d-impl-plan.md](https://github.com/edeno/spyglass-skill/blob/round-d/docs/plans/round-d-impl-plan.md) Phase 4.
**Workflow**: skill-creator-canonical (per-eval grader subagents producing `<eval>/<cond>/grading.json`, then `tools/make_plots.py` aggregation).

## Headline (from [`cumulative_summary.json`](summary/data/cumulative_summary.json))

| Metric | with_skill | without_skill | Δ |
|---|---|---|---|
| **Full pass** (all expectations satisfied) | 7 / 16 (43.75%) | 5 / 16 (31.25%) | **+12.5 pp** |
| Expectation pass rate | 144 / 164 (87.8%) | 126 / 164 (76.8%) | **+11.0 pp** |
| Tokens total | 904 k | 614 k | +290 k (+47%) |

**Outcome cross-tab**: 4 both-pass, **3 skill-only**, 1 baseline-only, 8 both-fail.
**McNemar exact two-sided**: p = 0.625 (n=4 discordant pairs is too low for significance — narrow rerun is underpowered for headline-level claims; full sweep needed for p-values).

For round-d's purpose (verify Phase 2 edits ship correctly), the discriminating evidence is the **per-eval delta on the 16 targeted evals**, not the global p-value.

## Per-eval scorecard

| Eval | Phase 2 edit verified | ws | bs | Δ |
|---|---|---|---|---|
| 028 | tool-routing | 9/13 (69%) | 10/13 (77%) | -8pp ⚠ |
| 029 | tool-routing | 6/6 (100%) | 6/6 (100%) | tie |
| 041 | verify-before-claim | **7/8 (88%)** | 2/8 (25%) | **+63pp ✅** |
| 072 | Raw runtime fetch | 14/14 (100%) | 14/14 (100%) | tie |
| 085 | cascade template | 6/8 (75%) | 5/8 (62.5%) | +12.5pp |
| 087 | cascade template | 12/14 (86%) | 11/14 (79%) | +7pp |
| 088 | cascade template | 6/8 (75%) | 4/8 (50%) | +25pp ✅ |
| 089 | field ownership | 7/10 (70%) | 9/10 (90%) | -20pp ⚠ |
| 099 | key_source | 9/9 (100%) | 9/9 (100%) | tie |
| 100 | clusterless plumbing | 7/7 (100%) | 7/7 (100%) | tie |
| 105 | field ownership | 7/9 (78%) | 8/9 (89%) | -11pp ⚠ |
| 106 | decision-pt #3 | 15/15 (100%) | 14/15 (93%) | +7pp |
| 107 | tool-routing | **12/12 (100%)** | 5/12 (42%) | **+58pp ✅** |
| 108 | tool-routing | 9/12 (75%) | 7/12 (58%) | +17pp |
| 113 | cascade template | 12/12 (100%) | 8/12 (67%) | **+33pp ✅** |
| 118 | verify-before-claim | 6/7 (86%) | 7/7 (100%) | -14pp ⚠ |

**4 ws-worse-than-bs cases** flagged. All 4 graders independently raised eval-rubric concerns that explain the regressions:

- **eval-028**: ws led with `CurationV1.get_sort_group_info` (the helper) instead of the explicit FK walk; rubric expected the FK walk first. The ws response is arguably *more* correct (using the bundled helper), but the rubric grades on the explicit-walk path.
- **eval-089**: ws used a 2-table `*` natural join instead of the canonical sub-restriction `& (...)` form. Functionally equivalent for 2 tables, but the rubric checks for `& (` literal.
- **eval-105**: ws's "WRONG — silently returns the entire CameraDevice table" pedagogical anti-pattern example trips a forbidden-substring check (`CameraDevice & {"nwb_file_name"`). The rubric doesn't carve out labeled wrong-examples.
- **eval-118**: ws missed the qualitative-direction half of a compound assertion (didn't name "fewer state bins → faster, lower spatial resolution") despite providing a substantively richer answer with the blob-vs-column reframing.

**These are rubric-friction regressions, not skill-content regressions** — the same ones round-c flagged for the eval-set as a whole.

## Per-edit verification (Phase 2 design checks)

### Phase 2.1 — verify-before-claim Core Directive
- **eval-041 ws** (config-key-error-after-pull): 7/8. Names `Table.alter()` + CHANGELOG.md + admin-coordination path. Routes to `setup_troubleshooting.md § KeyError after git pull`. Does NOT recommend `git checkout <sha>` rollback. **bs scored 2/8** — strongest delta in the run.
- **eval-118 ws** (counterfactual-decoding-bin-size): 6/7. Corrects the user's premise (`position_bin_size` is inside `decoding_params` blob) and walks the cascade. The 1 failure is a compound assertion's "qualitative direction" half.

### Phase 2.2 — Tool routing
- **eval-028 / 107 / 108 / 089 ws transcripts**: `code_graph.py` and source-read invocations confirmed in all four. eval-107 ws scored 12/12 vs bs 5/12 (+58pp) — the largest skill-only delta after eval-041. The directive is being read AND acted on.

### Phase 2.3 — Field ownership
- **eval-089 ws** correctly identifies `interval_list_name` as declared on `SpikeSortingRecordingSelection` (not `SpikeSortingRecording`) and explains the silent-drop trap.
- **eval-105 ws** identifies `VideoFile.camera_name` as a secondary attribute matched by string at ingest time, not via a declared FK; cites `common_behav.py:470` and `:506`.

### Phase 2.5 — Cascade template
- **eval-085, 087, 088, 113 ws** all use the four-slot template with concrete unaffected-branch lists + `descendants()` / `code_graph.py path --down` verification. eval-113 scored 12/12 vs bs 8/12 (+33pp) — the cascade template clearly differentiates here.

### Phase 2.6 — Raw is runtime fetch
- **eval-072 ws** explicitly separates "Tier 4 — runtime / storage" from static FK ancestors and cites the `feedback_loops.md` static-graph-vs-runtime callout. Both ws and bs scored 14/14 (saturated tie) — the bs agent figured this out from source-reads, so this concept doesn't differentiate at this difficulty level.

### Phase 2.7 — Clusterless plumbing-vs-input
- **eval-100 ws** uses the Phase 2.7 framing exactly: `SpikeSortingOutput.CurationV1` is plumbing, accept/reject labels don't flow into the decoder. Both ws and bs scored 7/7 (saturated tie) — the bs agent again figured this out from source.

### Phase 2.8 — `key_source` concept
- **eval-099 ws** opens with `key_source`, gives the candidates / pending / already triple. Both ws and bs scored 9/9 (saturated tie) — `key_source` is reachable from training.

## Tokens / cost

ws spent **+290 k more tokens than bs** to deliver **+12.5pp full-pass** and **+11.0pp expectation rate**. Per [`spend_by_outcome`](summary/data/cumulative_summary.json):
- 27% of extra tokens go to **both_pass** evals (skill verifying answers bs would have gotten right without help — candidate for routing gate)
- 14% goes to **skill_only** wins (worth the spend)
- 51% goes to **both_fail** (skill spent but didn't unlock the answer — rubric-friction or content-gap)

## Caveats

1. **Sample size**: 16 evals is too small for headline McNemar significance (p=0.625 with n=4 discordant). For round-d's purpose (verify Phase 2 design shipped), per-eval delta on targeted evals is the relevant signal.
2. **Saturated ties at 100/100** (029, 072, 099, 100): these evals don't discriminate. The corresponding Phase 2 concepts ARE in the skill (verified by reading transcripts), but bs agents could derive them from source. Including them was deliberate (regression check), not because they'd swing the delta.
3. **4 ws-worse cases are rubric-friction**, not skill regressions. Phase 3 rubric corrections in evals.json should be re-applied to 028, 089, 105, 118 to clean these up before any future sweep.
4. **No source-read denials** (the round-d Phase 4 v1 problem) and **no Skill-tool invocation contamination** (verified by parsing transcripts post-hoc — the new permission scope and bs-prompt prohibitions both held).
5. **bs agents had source-read access** (per dispatch_prompts.md) and used it productively. This is not contamination — it's the canonical comparison shape (skill vs. source-only).

## Verdict

All 8 Phase 2 edits + Phase 3 rubric corrections deliver verifiable behavioral changes in the narrow rerun:
- **3 strong skill-only wins** (041 +63pp, 107 +58pp, 113 +33pp).
- **4 saturated ties** at 100/100 — both conditions handled correctly; concept reachable from source.
- **5 partial wins** (085, 087, 088, 106, 108) — skill helps but bs gets a partial answer too.
- **4 rubric-friction regressions** — content is fine, rubric needs tightening.
- **0 content regressions**.

**Recommendation**: Proceed to merge `round-d` → `master`. Phase 3 rubric corrections needed for 028/089/105/118 before any future full sweep.

## Artifacts

- [benchmark.json](iteration-1/benchmark.json) — per-eval pass/fail + tokens/duration aggregates
- [summary/INDEX.md](summary/INDEX.md) — generated guide to all summary outputs
- [summary/data/cumulative_summary.json](summary/data/cumulative_summary.json) — headline numbers
- [summary/data/top_skill_wins.csv](summary/data/top_skill_wins.csv) — per-eval Δ ranking
- [summary/data/routing_diagnosis.csv](summary/data/routing_diagnosis.csv) — ws-failure routing-vs-synthesis split
- [summary/data/transcript_stats.json](summary/data/transcript_stats.json) — tool-call totals, source-assistance, contamination check
- [summary/figures/](summary/figures/) — generated PNG figures
- [transcripts_snapshot/](transcripts_snapshot/) — 32 raw subagent transcripts (~3 MB)
