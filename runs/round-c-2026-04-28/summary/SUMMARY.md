# Spyglass skill — 130-eval sweep summary and recommendations

Run date: 2026-04-28. Run id: `round-c-2026-04-28`. Skill: `skills/spyglass`. Eval set: `skills/spyglass/evals/evals.json` (130 evals × 2 conditions = 260 subagent runs across 7 stratified batches). Workspace: `runs/round-c-2026-04-28/iteration-{1..7}/` (in the `spyglass-skill-workspace` repo). Run metadata (skill commit, headline results, contamination notes): [`../run.json`](../run.json).

## Headline result

| | with skill | baseline | delta |
| --- | --- | --- | --- |
| Evals fully pass | **111 / 130 (85.4%)** | 83 / 130 (63.8%) | **+28 evals (+21.5pp)** |
| Expectations | 989 / 1032 (95.8%) | 895 / 1032 (86.7%) | +9.1pp |
| Tokens (total) | 5.20M | 3.15M | total 8.35M (~$200) |
| Mean tokens / run | 40.0k | 24.2k | +65% |
| Mean wall-clock / run | 80s | 65s | +23% |

The skill costs ~65% more tokens per run and converts that into a +21.5pp absolute lift in full-eval pass rate (111 vs 83 evals out of 130) and a +9.1pp lift on the harder per-expectation rubric. Absolute spend on 130 evals × 2 conditions: ~$200.

See [05_cumulative_summary.png](05_cumulative_summary.png) for the headline plot.

## Plots

**Per-batch view:**

1. [01_per_batch_pass_rate.png](01_per_batch_pass_rate.png) — full-eval pass rate per batch.
2. [02_delta_per_batch.png](02_delta_per_batch.png) — behavioral and expectation delta per batch.
3. [03_per_eval_outcomes.png](03_per_eval_outcomes.png) — per-eval outcome stack (both pass / skill-only / baseline-only / both fail).
4. [04_cost_per_batch.png](04_cost_per_batch.png) — mean tokens and wall-clock per run.

**Headline:**

5. [05_cumulative_summary.png](05_cumulative_summary.png) — final cumulative result, all 130 evals.

**Category breakdowns:**

6. [06_by_category.png](06_by_category.png) — pass rate by stage and by tier.
7. [07_by_difficulty.png](07_by_difficulty.png) — pass rate and outcomes by difficulty (easy / medium / hard).
8. [08_difficulty_x_stage_heatmap.png](08_difficulty_x_stage_heatmap.png) — skill delta as a stage × difficulty heatmap.

**Per-eval views:**

9. [09_per_eval_scatter.png](09_per_eval_scatter.png) — scatter of skill vs baseline, each dot one of 130 evals, colored by difficulty.
10. [10_top_skill_wins.png](10_top_skill_wins.png) — eval-level extremes (top 15 skill wins + the largest skill-underperformance cases by expectation delta).

**Skill-internal:**

11. [11_reference_utilization.png](11_reference_utilization.png) — % of with_skill runs that opened each reference file (parsed from snapshotted subagent transcripts).
12. [12_script_utilization.png](12_script_utilization.png) — bundled-script invocations and source-only reads, per script, across all with_skill runs.

Underlying numbers: [category_breakdown.csv](category_breakdown.csv) (covers stage, tier, and difficulty breakdowns).

## Where the skill helps most — by category

Per-stage delta (full-eval pass rate, sorted by skill lift):

| Stage | n | with skill | baseline | Δ pp |
| --- | --- | --- | --- | --- |
| **ingestion** | 4 | 4 / 4 (100%) | 0 / 4 (0%) | **+100** |
| **table-understanding** | 4 | 4 / 4 (100%) | 1 / 4 (25%) | **+75** |
| **setup** | 7 | 6 / 7 (86%) | 1 / 7 (14%) | **+71** |
| non-activation | 2 | 2 / 2 (100%) | 1 / 2 (50%) | +50 |
| pipeline-authoring | 7 | 3 / 7 (43%) | 0 / 7 (0%) | +43 |
| **hallucination-resistance** | 11 | 11 / 11 (100%) | 8 / 11 (73%) | **+27** |
| parameter-understanding | 9 | 7 / 9 (78%) | 5 / 9 (56%) | +22 |
| common-mistakes | 6 | 6 / 6 (100%) | 5 / 6 (83%) | +17 |
| destructive-operations | 6 | 3 / 6 (50%) | 2 / 6 (33%) | +17 |
| pipeline-usage | 44 | 35 / 44 (80%) | 31 / 44 (70%) | +9 |
| runtime-debugging | 21 | 21 / 21 (100%) | 20 / 21 (95%) | +5 |
| framework-concepts | 9 | 9 / 9 (100%) | 9 / 9 (100%) | 0 |

Per-tier delta (top 10 by lift, where n ≥ 3):

| Tier | n | with skill | baseline | Δ pp |
| --- | --- | --- | --- | --- |
| post-ingest-validation | 3 | 3 / 3 | 0 / 3 | +100 |
| config-troubleshooting | 3 | 2 / 3 | 0 / 3 | +67 |
| environment-triage | 4 | 4 / 4 | 2 / 4 | +50 |
| table-classification | 6 | 6 / 6 | 3 / 6 | +50 |
| parameter-semantics | 8 | 7 / 8 | 4 / 8 | +37 |
| adversarial | 17 | 13 / 17 | 8 / 17 | +29 |
| baseline | 7 | 6 / 7 | 4 / 7 | +29 |
| atomic-read | 8 | 7 / 8 | 5 / 8 | +25 |
| resource-selection | 4 | 3 / 4 | 2 / 4 | +25 |
| joins | 9 | 8 / 9 | 6 / 9 | +22 |

Per-difficulty delta:

| Difficulty | n | with skill | baseline | Δ pp |
| --- | --- | --- | --- | --- |
| easy | 35 | 33 / 35 (94%) | 25 / 35 (71%) | **+23** |
| medium | 62 | 54 / 62 (87%) | 40 / 62 (65%) | **+23** |
| hard | 33 | 24 / 33 (73%) | 18 / 33 (55%) | **+18** |

Worth noting: **the skill helps roughly equally across difficulty levels** (+18 to +23pp), and *both* conditions degrade with difficulty. The skill does not specialize for hard prompts — it provides similar lift across the board.

The stage × difficulty heatmap ([08_difficulty_x_stage_heatmap.png](08_difficulty_x_stage_heatmap.png)) reveals where the lift is concentrated within hard prompts:

- **Hard ingestion + hard setup**: +100pp (1/1 each — small n but consistent direction)
- **Hard pipeline-authoring**: +50pp (4 evals) — biggest hard-eval surface
- **Hard parameter-understanding**: +17pp on 6 hard evals (where eval-118 lives — the lift would be larger without that single ws-worse outlier)
- **Hard pipeline-usage**: +0pp on 11 evals — model is solidly competent on hard pipeline-usage; skill marginal
- **Hard runtime-debugging**: +0pp on 7 evals — confirms baseline-strong cluster

Per-tier ties (where the skill provided no measurable lift on the binary rubric):

| Tier | n | with skill | baseline | note |
| --- | --- | --- | --- | --- |
| runtime-errors | 10 | 10 / 10 | 10 / 10 | both 100% — model has these symptoms in training |
| schema-introspection | 7 | 7 / 7 | 7 / 7 | both 100% — schema facts are well known |
| counterfactual | 7 | 5 / 7 | 5 / 7 | both correct on most; the 2 misses are split symmetrically |
| dependency-tracing | 6 | 4 / 6 | 4 / 6 | both miss `Raw` on FK walks |
| compound | 4 | 3 / 4 | 3 / 4 | similar reasoning shape; skill marginal |
| merge-key-discovery | 3 | 3 / 3 | 3 / 3 | both got these |
| workflow-position | 3 | 2 / 3 | 2 / 3 | tied |
| workflow-recovery | 3 | 2 / 3 | 2 / 3 | tied |

## Failure modes worth fixing

### 1. Source-skepticism over-applied (eval-118 and eval-041)

Two of the largest negative expectation deltas share one shape: the model loaded the skill, decided the question warranted a verify-before-claim caveat, and never named the most-likely answer first. Concretely:

- **eval-118** (counterfactual decoding `position_bin_size`): skill response opens "let me verify whether `position_bin_size` is even a real field" and spends a section on source-skepticism, never naming the qualitative cascade direction (coarser bins → fewer state bins → faster, lower spatial resolution).
- **eval-041** (`KeyError: 'pipeline'` after `git pull`): skill response opens "probably not in-DB schema drift" and demotes schema drift to the third-priority hypothesis (preferring stale params blobs / half-upgraded install). Then explicitly recommends `git checkout <yesterday's-sha>` — exactly what the eval forbids.

Both are generation-time choices, not skill-content gaps. The verify-before-claim Core Directive is being applied as "verify first, then maybe answer" instead of "state the most-likely answer first, *then* verify." Fix is a small clarification in `SKILL.md` Core Directives.

A third small underperformance case, **eval-106** (PFC + W-track compound query), was not the same failure mode: baseline passed 15/15 while with_skill got 14/15, missing a narrow projection/detail check. It is better treated as rubric-level friction than a new skill-design theme.

### 2. Two specific reference-coverage gaps surfaced

- **eval-072** (LFPBandV1 dependency walk): both conditions failed to name `Raw` because the static FK graph in `code_graph.py path --up` doesn't surface the runtime fetch in `LFPV1.make()`. Reference fix: note in `lfp_pipeline.md` that `Raw` is a runtime dependency not a static FK, and that static graph output must be paired with a source read of `make()` when the user asks what is needed to *recreate populated data*.
- **eval-100** (post-curation clusterless workflow): both conditions get the precise relationship between curation and clusterless decoding wrong, but in *opposite* directions — skill assumes a full accepted-unit curation is required, baseline says curation is optional/unnecessary. Both are too strong. The source-accurate position is more nuanced:

  - `UnitWaveformFeaturesSelection` FKs into `SpikeSortingOutput.proj(spikesorting_merge_id="merge_id")` — i.e. the merge entry, not directly to `SpikeSorting`.
  - The v1 waveform-features `make()` reads from `SpikeSortingOutput.CurationV1` to recover the upstream `sorting_id`, so a `CurationV1`-backed merge row must exist on the `SpikeSortingOutput` table before features can be computed.
  - But the *scientific* input to clusterless decoding is the per-spike waveform features, not the curated accepted-unit labels. So unit acceptance/rejection from curation does not flow into the decoder; an initial-curation-only run is enough.

  Reference fix: add a `decoding_pipeline.md` callout that distinguishes (a) the **plumbing requirement** — clusterless decoding needs a `CurationV1`-backed `SpikeSortingOutput` merge row as the provenance/merge wrapper before `UnitWaveformFeatures.populate()` will run — from (b) the **scientific input** — clusterless uses waveform features, not the unit-acceptance labels from curation. "Curation is required" and "curation is bypassed" are both wrong; the right framing is "an initial curation that registers the sort in `SpikeSortingOutput.CurationV1` is required as merge-table provenance; the *content* of curation labels does not flow into clusterless decoding."

## What did the skill machinery actually get used?

Reference and bundled-script utilization measured by parsing every with_skill subagent's transcript (`Read` / `Bash` tool calls; n=134 runs). See [11_reference_utilization.png](11_reference_utilization.png) and [12_script_utilization.png](12_script_utilization.png).

Note on the run count: the headline 130 evals × 2 conditions = 260 dispatches refers to **graded** runs. The transcript count is **267** (134 with_skill + 133 without_skill) because retry attempts retained separate agent IDs in `.agent_map.json`; in the current workspace, the retained extras are concentrated in iteration-3 (47 transcripts for 40 expected runs, +7). Utilization analysis parses all 267 transcripts; per-eval grading uses one successful run per eval. That's why benchmark.json shows 130 unique evals while transcript-derived counts are slightly higher.

**Reference files (top loaders):**

| Reference | % of ws runs that opened it |
| --- | --- |
| `SKILL.md` | 97% (the entry point — opened by directive) |
| `lfp_pipeline.md`, `merge_methods.md`, `decoding_pipeline.md` | ~10% each |
| `common_tables.md`, `spikesorting_v1_pipeline.md`, `destructive_operations.md`, `ripple_pipeline.md` | 8–10% each |
| `runtime_debugging.md`, `position_pipeline.md`, `datajoint_api.md` | 6–7% each |
| Long tail (15+ refs) | <5% each |

The progressive-disclosure pattern is doing what it should: `SKILL.md` is the routing layer (97% utilization), and individual references are pulled in only when the prompt warrants. No reference dominates — the skill is broad rather than concentrated.

**Bundled scripts (utilization across 134 with_skill runs):**

| Script | Role | Executions | Runs that used it |
| --- | --- | --- | --- |
| `code_graph.py` | agent-facing (static FK / source walker) | 47 | 21 / 134 (15.7%) |
| `db_graph.py` | agent-facing (live-DB introspection) | 9 | 2 / 134 (1.5%) |
| `scrub_dj_config.py` | agent-facing (password-safe config viewer) | 0 | 0 |
| `verify_spyglass_env.py` | agent-facing (env sanity-check) | 0 | 0 |
| `validate_skill.py` | maintainer (validator) | 0 | 0 |
| `validate_all.sh` | maintainer (validator runner) | 0 | 0 |
| `_index.py` | maintainer (index builder) | 0 | 0 |

**Headline:** **23 / 134 ws runs (17%) executed at least one bundled script.** Baseline runs executed zero (as expected — they have no skill exposure).

The matcher counts only **execution context** (`python … script.py`, `bash … script.sh`, `./script.py`) — bare mentions of a script's filename inside a `grep` / `cat` / `head` / `ls` command don't count. Maintainer-facing scripts (`validate_skill.py`, `validate_all.sh`, `_index.py`) correctly show 0 — eval agents should never run those, and they don't.

**What the script-utilization data tells us:**

1. **`code_graph.py` is the high-value script** — 47 invocations across 21 runs, the static FK / source-walker. Often invoked multiple times in one run as the agent traces dependency chains. Worth promoting for class identity, static dependency paths, and source locations. But eval-072 shows the boundary: static graph output is not enough for runtime dependencies hidden inside `make()`; the right pattern is `code_graph.py` to locate the path, then source-read the relevant `make()` body for runtime fetches.
2. **`db_graph.py` low utilization is structural, not low value.** It needs a live MySQL connection. Eval agents have no DB; the script is *mentioned* in answers more often than it's *run* (9 invocations + 3 source-only reads). This is the right shape — the skill correctly tells users to run it; the script can't run itself in eval conditions.
3. **`verify_spyglass_env.py` was never invoked.** Same diagnosis as `db_graph.py` — needs an env that eval agents don't have. Worth keeping for users.
4. **`scrub_dj_config.py` was never executed**, despite Core Directive #6 telling agents to use it whenever asked to inspect a DataJoint config. The eval that should exercise it (eval-022, password-exposure) had the with_skill agent recommend the script in its prose answer but stop short of running it. That's a real discoverability gap: the script is bundled and documented, but agents are reasoning through it rather than executing it. Worth tightening Core Directive #6 to include the literal command form (e.g., `python skills/spyglass/scripts/scrub_dj_config.py ~/.datajoint_config.json`) so the agent has a copy-pasteable invocation rather than a script name.
5. **Maintainer-facing scripts** (`validate_skill.py`, `validate_all.sh`, `_index.py`) correctly showed **0 executions** from eval agents — they're for the skill maintainer's pre-commit gate, not for users. (An earlier loose-match version of this analysis double-counted a `grep validate_skill.py …` source-search as an "invocation"; the current matcher requires actual execution context, which fixes the false positive.)

### Transcript-level caveats and mechanisms

Five observations from the snapshotted transcripts that change how the headline numbers should be read:

1. **The baseline was source-assisted, not pure parametric memory.** 45 / 133 baseline runs (~34%) touched the Spyglass source — either reading files under `/Documents/GitHub/spyglass/src/spyglass/` (41 runs) or WebFetching GitHub Spyglass (4 runs). The skill lift is therefore *not* "skill vs model memory" — it's "skill vs model + Spyglass source access, but no skill routing/reference layer." That's a tighter comparison and makes the +21.5pp full-eval delta more meaningful: a baseline that could read source still missed where the routing layer (references + bundled scripts + Core Directives) directs the agent.

2. **Minor baseline contamination occurred in 5 / 133 runs.** Despite the without_skill prompt instructing agents not to consult the skill bundle, five baseline transcripts touched it: eval-058 directly read `ripple_pipeline.md` (the most consequential — it's a full reference); eval-034 grepped the references directory; eval-042 / 066 / 082 listed the references or scripts directories. Direction of bias: this likely biases *against* the skill (baseline got partial skill-content access on those evals, narrowing the measured gap), not in favor of it. Worth flagging as a data-integrity caveat for any reader interpreting per-eval deltas.

3. **No evidence of skill-activation failure in graded runs.** SKILL.md was read in **130 / 130 unique with_skill graded evals** — not 97%. The earlier 97% figure divided by *all 134 with_skill transcripts* (which counts retries with separate agent IDs); reading at the eval level shows every successful graded run loaded SKILL.md. The benchmark thus did not expose an activation failure; failures inside graded runs are content/routing failures, not "the skill didn't trigger" failures.

4. **The extra cost is exploration, not just answer length.** With_skill transcripts had ~2.5× more tool calls than baseline: 538 Read + 582 Bash (1,120 total) vs 139 Read + 312 Bash (451 total). The +65% mean-token and +23% mean-wall-clock costs aren't from longer answers — they're from agents inspecting more references, running more scripts, and source-reading more often. That's the right cost shape to buy correctness with, and supports keeping the cost contour as a maintainer note (rec #16) rather than a user-facing warning.

5. **Most remaining ws misses loaded the right reference but didn't escalate to verification.** Failed with_skill runs typically had SKILL.md plus the topically-correct pipeline / destructive / custom reference loaded, but no follow-up source-read or `code_graph.py` / `db_graph.py` / `.heading` invocation. The misses are "agent read the prose and stopped," not "agent never reached the right reference." This is the strongest evidence yet for the routing/templates direction over more reference prose: recommendations #6 (tool routing), #7 (field ownership), and #8 (cascade template) are about *when to escalate from prose to verification*, not about adding more prose. Adding more reference text would not have helped these runs; the runs already loaded enough text — they didn't move from text to evidence.

## Recommendations — apply skill-creator best practices

These follow two skill-design principles applied throughout this analysis: (a) keep the skill text lean and explain *why* — never overconstrain with rigid MUSTs; (b) generalize from the eval feedback, not overfit to it. In rough priority order:

### Priority A — Round-D edits (high yield, low effort)

1. **Clarify Core Directive on verify-before-claim.** Current phrasing reads as "verify before claiming." Reframe as **"State the most-likely answer first; then verify the high-stakes claims."** The intent is to gate confident assertions on evidence, not to gate *answering at all*. Cite eval-118 / eval-041 in the SKILL.md commit message so future maintainers understand why the clarification exists. *Best-practice rationale:* explain the *why* — current rule is being mis-applied because the underlying intent isn't visible.

2. **Reference-coverage patch for eval-072 and eval-100.** Two surgical edits:
   - `references/lfp_pipeline.md` — note that `Raw` is a runtime dependency (read inside `LFPV1.make()`) not a static FK target. Add a one-line callout where the FK chain is documented.
   - `references/decoding_pipeline.md` — add a "Clusterless: what's needed from curation" callout that splits the **plumbing requirement** from the **scientific input**. Plumbing: `UnitWaveformFeaturesSelection` FKs `SpikeSortingOutput.proj(spikesorting_merge_id="merge_id")`, and the v1 waveform-features `make()` reads from `SpikeSortingOutput.CurationV1` to recover `sorting_id`, so a `CurationV1`-backed merge row must exist before features compute. Scientific input: the per-spike waveform features are what flow into the decoder, not the accepted-unit labels — so an initial curation that registers the sort in the merge table is enough; ongoing accept/reject curation does not change the clusterless result. Avoid the binary "curation is required" / "curation is bypassed" framings — both are wrong, and eval-100 caught the skill on the first one.

3. **Frontmatter trigger audit.** The skill description is what triggers the skill (or doesn't) on a fresh prompt. Review the current `SKILL.md` frontmatter against the live eval set and near-miss non-Spyglass prompts; update it only if activation misses or false activations show up. *Best-practice rationale:* the description's only job is triggering — measure it, don't guess.

### Priority B — strategic skill content additions (medium effort)

4. **Stop expanding low-yield surfaces.** Three eval clusters showed near-zero skill lift: `runtime-errors` (10/10 both), `schema-introspection` (7/7 both), `counterfactual` (5/7 both). The model already has these from training. Time spent expanding `runtime_debugging.md` / `common_tables.md` / one-off counterfactual examples (i.e. additional individual cases without a reusable template — recommendation #8 below adds the *template*, which is different) is **lower-yield than** time spent on:
   - `setup_*` references (Batch 7's biggest wins live here)
   - Adversarial-hallucination scenarios (Batch 1, 2 wins)
   - Lab-specific helper APIs (`SortedSpikesGroup.create_group`, `AnalysisNwbfile.build()`, `scrub_dj_config.py`, `verify_spyglass_env.py`)

5. **Watch the "bundle a script vs document a pattern" tradeoff.** Several wins traced to specific scripts the skill bundles (`scrub_dj_config.py`, `db_graph.py`, `code_graph.py`). When a future eval shows multiple subagents independently re-implementing the same diagnostic snippet, that's the strongest signal to bundle it as a script instead of documenting it inline. *Best-practice rationale:* one bundled script saves every future invocation from reinventing the wheel.

6. **Add a tool-routing Core Directive to SKILL.md** (covers eval-028 / 029 / 107 / 108 / 089 and the broader "wrong subcommand" failure mode). Script-utilization data ([12_script_utilization.png](12_script_utilization.png)) shows `code_graph.py` is the dominant agent-facing tool (47 invocations / 21 runs) but under-invoked on a class of questions where it would have been the right tool — the brain-region-for-sorted-spikes family had **zero** `code_graph.py` invocations, and eval-029 invoked it with the wrong subcommand (`describe` instead of `path --to`). The fix is a generalized routing rule, not a per-eval reference example.

   > **Tool routing for relationship and lookup questions:**
   > - *"How does X relate to Y?"* (joins, FK chains, table-to-table relationships) → run `code_graph.py path --to X Y` and **translate the printed path into a DataJoint restriction/join expression**. FKs are directed: if X→Y returns no path, flip and try Y→X. Note: `path --to` answers *table-level* relationship questions, not column-level provenance — for "which table declares this field?", see field ownership (rec #7).
   > - *"What's on table X?"* (fields, tier, methods, FKs on one class — including which fields are PK vs secondary) → run `code_graph.py describe X` or read `Table.heading`. Don't use `describe` for relationship questions — it returns one class's view, not a path between two.
   > - *"What's the runtime behavior inside `make()`?"* (which fields a `Computed.make()` actually fetches, what blob keys a parameter row's `params` dict carries) → source-read the relevant `make()` body. The static graph and `describe` only show the *declared* schema, not the runtime fetches/uses.
   > - *"What rows / values are actually in the DB?"* → run `db_graph.py find-instance ...` (or `db_graph.py describe` for live-DB attribute info) if a live DB is available; otherwise hand the user the query and ask them to run it. Don't invent row values.

   The "translate the path into a DataJoint expression" clause is load-bearing — without it, agents that *do* run the script can stop at "the script told me the path" and never produce the `(A * B * C & key)` expression the user can run. **Explicit non-action**: do NOT add a bespoke brain-region worked example to any reference. The general rule is more valuable than the BrainRegion case the eval surfaced (`Subject`, `LabMember`, `Probe`, `Task`, `Device` all share the same shape). Re-evaluate only if the routing rule fails to lift these evals after revision.

7. **Add a field-ownership-before-query Core Directive to SKILL.md** (covers #89 directly; same shape would have caught #105 and prevents key-hygiene-mutated-into-ownership errors). Verified against the Spyglass source checkout used for this eval sweep (re-verify against the upstream commit you're currently bumping to before treating as canonical, since v1 schema fields can drift across releases): `SpikeSortingRecordingSelection` declares `recording_id` as PK; `nwb_file_name` and `interval_list_name` appear as secondary attributes introduced by FK references (`-> Raw`, `-> IntervalList`) below the `---` divider. `SpikeSortingRecording` FKs only `recording_id`, so it does **not** declare those names as restriction-safe attributes. The skill response in eval-089 ws restricted `SpikeSortingRecording & {"interval_list_name": ...}` and fetched `nwb_file_name` from there — wrong table for the field, even if the generated code looks plausible (we did not live-verify runtime behavior; the static source says the field is not declared there).

   > **Field ownership before query generation:**
   > When writing a join or restriction, every attribute used as a join key or in a restriction dict must be traced to the table that declares it. DataJoint FK inheritance only safely propagates **primary-key** fields; secondary attributes on an upstream table do **not** automatically become restriction-safe on downstream tables. The most common trap is reused names — `nwb_file_name`, `interval_list_name`, `merge_id`, `electrode_id` — appearing on multiple tables with different declaration sites. If you can't cite where a field is declared, treat the query as a hypothesis and verify via `code_graph.py describe <Table>`, source-read, or the table's `.heading` before claiming the query works.

   Two distinct failure modes this rule must guard against (both seen in evals): (a) **wrong owner for a real field** — what eval-089 hit; (b) **invented ownership of a real field**. Both have the same fix.

8. **Add a counterfactual / recovery / parameter-swap cascade template to `references/destructive_operations.md`** (covers #85, #87, #88, #113, and the recovery-template gap behind several others). When explaining "what changes if I re-run with new params" or "what cascades when I delete X" or "how do I recover from an in-place edit," the response must include all four slots:

   - **The new row / new merge_id** that the new computation produces (and that the old row is *not* mutated).
   - **Downstream branches that must be re-selected and re-populated** to pick up the change (referenced by name, not by category).
   - **Unaffected sibling and upstream branches** — explicitly enumerated, because "what survives" is what the user can re-use.
   - **`Table.descendants()` / `Table.ancestors()` (or `db_graph.py path --down <Class>` / `db_graph.py path --up <Class>` against a live DB)** as the verification step — names the actual DataJoint method or the live-DB path traversal, not "walk the graph."

   This collapses what looked like four separate routing misses into one template gap. The references that need the link to this template are `decoding_pipeline.md`, `ripple_pipeline.md`, `position_pipeline.md`, `lfp_pipeline.md`, `spikesorting_v1_pipeline.md` — anywhere a counterfactual / recovery / parameter-swap question is plausible.

9. **`scrub_dj_config.py` literal-command discoverability.** Make Core Directive #6 include the literal command form (e.g., `python skills/spyglass/scripts/scrub_dj_config.py ~/.datajoint_config.json`) rather than just naming the script. The eval-022 ws response talked *about* the script without running it; agents reach for copy-pasteable invocations.

10. **Group-table routing.** Strengthen the routing row for "all units/spikes across tetrodes/sort groups" so it loads `group_tables.md` plus `spikesorting_v1_analysis.md`. The failure in eval-108 was not "what is `SortedSpikesGroup`?" but "derive hippocampal sort groups before calling `create_group()`."

11. **`key_source` concept callout in `references/runtime_debugging.md`.** A populate that silently returns zero rows because `key_source` is empty has no diagnostic path without that DataJoint vocabulary. eval-099 surfaces the concept gap; the right fix is the concept callout, **not** a literal-substring requirement in the eval rubric (the substantive answer is otherwise complete).

### Priority C — eval-set hardening (low effort, helps future runs)

12. **Promote the 14 substring relaxations to a single normalized pass.** Across the sweep we relaxed 7 substrings in commit 8b3fa1b (Batch 5), 6 in Batch 7, 1 in Batch 4. The pattern is consistent: literal phrasing assertions over-fire on synonym-rich responses. Going forward, prefer behavioral checks for anything but mandatory-mention of a specific Spyglass identifier (class name, file path, error string).

13. **Add a behavioral check to eval-041 explicitly forbidding `git checkout <sha>` rollback.** Currently the rule fires symmetrically against both conditions (skill and baseline both lost the same check). Reframe so the eval checks "names CHANGELOG / Table.alter() / pip install -e ." as the canonical fix, not just "doesn't recommend rollback."

14. **Rubric correction for eval-060: `.describe()` is the wrong tool for blob-bearing param tables.** `(TrodesPosParams & key).fetch1("params")` plus a source-read of the relevant `make()` is the right shape — `.describe()` and `.heading` only show that there's a `params` blob column, not what keys live inside it. The current rubric requires `.describe()`/`.heading` literally; the eval should change to prefer the fetch + source-read pattern. This is **primarily a rubric fix**, but optionally a one-line generic note in `references/datajoint_api.md` ("for blob-bearing param tables, prefer `fetch1('params')` + source-read of the consumer; `.describe()`/`.heading` only confirms a blob column exists") is worth adding because the pattern recurs across `RippleParameters`, `DecodingParameters`, `WaveformFeaturesParams`, `MetricParameters` — every blob-bearing param table in Spyglass.

15. **Don't require the literal `key_source` substring in eval-099** (or any eval where the substantive answer is otherwise complete). The concept callout from recommendation #11 lives in `runtime_debugging.md`; the eval should test for the concept (e.g., behavioral check: "names a way to debug a populate() that silently produces zero rows"), not the literal token.

16. **Document the cost contour in maintainer notes, not necessarily in `SKILL.md`.** Overall the skill used +65% mean tokens and +23% mean wall-clock per run; some clusters were closer to 2x tokens. This is useful context for benchmark planning. It probably does **not** belong in the user-facing skill preamble unless users have a real opt-out path; keep `SKILL.md` focused on behavior.

### Priority D — operational notes for future eval sweeps

17. **Plan dispatches around token rate-limit windows.** Two batches (3 and 7) hit the rate limit mid-dispatch ("resets at 10:30am" and "resets at 3:30pm"). At ~40-parallel-dispatch batch sizes, allow a 30-minute retry buffer. Smaller batch sizes (~20) avoid this entirely but double wall-clock.

18. **The eval set is sufficient for round-D, but narrow coverage gaps remain.** 130 evals is saturated for the current high-priority claims; adding more generic pipeline-usage evals will dilute the signal (Batch 3 was already a tie). New evals should target specific skill *claims* not yet rubric-tested — e.g., the "verify before claim" clarification from rec #1 deserves 2-3 negative-example evals; the field-ownership rule from rec #7 deserves 2-3 evals where a "real-table-wrong-owner-field" trap is set (the `interval_list_name` / `nwb_file_name` / `merge_id` / `electrode_id` shapes). If expanding later, focus on low-utilization references that had little direct prompt coverage: FigURL, linearization, MUA, behavior/MoSeq, and export.

## Operational ledger

- **Total runs:** 260 subagent dispatches (130 evals × 2 conditions).
- **Token rate-limit hits:** 7/40 in Batch 3 (~17.5%), 15/60 in Batch 7 (~25%). All retried successfully.
- **Stalls (>600s no progress):** 3 total (Batch 2 bs-076, Batch 5 ws-118, Batch 7 ws-088). All retried successfully on second dispatch.
- **Substring relaxations applied:** 14 across 12 evals (commits 178f678, 0cb131d, 8b3fa1b, plus 7 in this run pending commit).

## Files

- [BATCHES.md](../BATCHES.md) — per-batch ledger.
- [findings.md](../findings.md) — cross-batch qualitative narrative.
- [iteration-N/benchmark.json](../iteration-1/benchmark.json) — per-batch aggregated stats (one per batch).
- [iteration-N/grader_summary.md](../iteration-1/grader_summary.md) — behavioral grader's per-batch report (one per batch).
- [make_plots.py](make_plots.py) — re-runs the figures: `uv run --with matplotlib --with numpy python make_plots.py`.
