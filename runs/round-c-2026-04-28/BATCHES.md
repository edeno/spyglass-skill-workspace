# Eval batch ledger

Plan: run all 130 evals × 2 conditions (with-skill, without-skill = 260 subagent runs) in 7 stratified batches of ~20 evals each. Highest-signal batches first.

**Per-batch flow:** create `iteration-<N>/eval-<ID>/{with_skill,without_skill}/`, dispatch all subagents in parallel, capture timing notifications, grade, aggregate to `iteration-<N>/benchmark.json`, then append the summary row below. Stop after each batch.

**Resume semantics:** if a batch is interrupted, `iteration-<N>/eval-<ID>/.../timing.json` files mark which runs completed. Re-running spawns only the missing ones.

## Batch plan

| Batch | Iteration dir | Scope | Eval IDs | Status | With-skill pass rate | Baseline pass rate | Δ | Tokens | Notes |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | `iteration-1/` | Key hygiene + merge gotchas (Batch D + adjacent) | 124, 125, 126, 127, 128, 129, 130, 14, 15, 16, 35, 49, 50, 51 (14 evals) | **DONE** | 100.0% | 92.5% | +7.5pp | 1,010,227 | with_skill 14/14 full-pass, baseline 11/14; eval-130 the largest delta (ws 6/6 vs bs 0/6); no regressions; re-graded after eval-125/129 forbidden-substring relaxation (commit 178f678) |
| 2 | `iteration-2/` | Hallucination resistance + common mistakes + framework concepts | 21, 78, 79, 80, 81, 115, 122, 123, 5, 25, 30, 7, 73, 74, 75, 76, 77, 96, 97, 109 (20 evals) | **DONE** | 100.0% | 94.4% | +5.6pp | 1,371,749 | with_skill 20/20 full-pass, baseline 17/20; biggest delta on eval-081 v0/v1 naming-extrapolation (ws 8/8 vs bs 3/8 — baseline confidently fabricated `SpikeSortingV1`); no regressions; re-graded after eval-021/096 substring relaxation (commit 0cb131d) |
| 3 | `iteration-3/` | Pipeline usage round 1 | 6, 9, 10, 11, 12, 13, 17, 18, 19, 26, 28, 29, 62, 63, 64, 67, 68, 69, 70, 71 (20 evals) | **DONE** | 100.0% | 100.0% | +0.0pp | 881,286 (partial — 25/40 timings) | with_skill 20/20 full-pass, baseline 20/20; pipeline-usage / atomic / disambiguation evals don't expose skill advantage at binary pass-fail level (qualitative wins on source-line citations, v0/v1 precision); no regressions; 7 runs needed retry after token rate limit |
| 4 | `iteration-4/` | Pipeline usage round 2 | 72, 85, 87, 89, 90, 91, 92, 93, 94, 95, 98, 99, 100, 102, 103, 104, 105, 106, 108 (19 evals) | **DONE** | 90.3% | 80.6% | +9.7pp | 1,309,738 | with_skill 10/19 full-pass, baseline 7/19; behavioral ws 54/63 vs bs 44/63 (+15.9pp); skill wins on joins/atomic-read (eval-095 +2, eval-102 +2, eval-094 +2); ties on table-usage easies (090-093); 1 forbidden-substring relaxation (eval-102 — guardrail-mention false positive); no ws-worse outliers |
| 5 | `iteration-5/` | Pipeline usage round 3 + parameter understanding | 57, 58, 59, 60, 61, 116, 117, 118 (8 evals) | **DONE** | 94.7% | 86.0% | +8.7pp | 644,041 | with_skill 6/8 full-pass, baseline 5/8; behavioral ws 29/32 vs bs 28/32 (+1); real skill wins on eval-061 (multi-shank v0/v1 + SpikeInterface failure mode) and eval-116 (RippleLFPSelection no-rebuild + provenance); outlier eval-118 ws 2/4 vs bs 4/4 (skill response got distracted by source-skeptical caveats); 7 over-strict literal-phrasing substrings relaxed in evals.json after grader review |
| 6 | `iteration-6/` | Runtime debugging | 3, 4, 27, 31, 36, 37, 38, 39, 43, 44, 48, 52, 65, 82, 84, 86, 101, 119, 120 (19 evals) | **DONE** | 100.0% | 97.5% | +2.5pp | 1,459,488 | with_skill 19/19 full-pass, baseline 18/19; only baseline miss is eval-082 (literally asks "which reference file inside the spyglass skill" — a skill-only artifact baseline cannot satisfy); behavioral checks ws 93/93 (100%) vs bs 91/93 (97.85%); confirms hypothesis that runtime-debugging baseline matches well on individual diagnoses, skill wins via routing only |
| 7 | `iteration-7/` | Setup / ingestion / pipeline-authoring / destructive / table-understanding / non-activation | 1, 2, 8, 20, 22, 23, 24, 32, 33, 34, 40, 41, 42, 45, 46, 47, 53, 54, 55, 56, 66, 83, 88, 107, 110, 111, 112, 113, 114, 121 (30 evals) | **DONE** | 90.3% | 67.9% | +22.4pp | 1,681,278 | with_skill 22/30 full-pass, baseline 5/30; behavioral ws 104/113 vs bs 74/113 (+26.5pp — largest behavioral spread of sweep); blowout wins on eval-107 (5/0), eval-045 (5/1), eval-032 (4/1); one ws-worse outlier eval-041 (1/5 vs 3/5 — skill response opens "probably not schema drift" and misses CHANGELOG.md routing); 6 substring relaxations applied (eval-23 fetch(as_dict=True), eval-54/55 phrasing, eval-110/111/114 Non-Negotiable); 15 of 60 hit token rate limit mid-batch and were retried successfully |

## Per-batch eval roster

### Batch 1 — Key hygiene + merge gotchas (Batch D + adjacent)

- **id=124** `key-hygiene-singular-plural-typo` (stage=hallucination-resistance, tier=schema-introspection, diff=easy)
- **id=125** `key-hygiene-blob-key-not-heading` (stage=parameter-understanding, tier=parameter-semantics, diff=medium)
- **id=126** `key-hygiene-merge-master-silent-no-op` (stage=common-mistakes, tier=merge-table-gotchas, diff=medium)
- **id=127** `key-hygiene-partial-populate-scope` (stage=pipeline-usage, tier=disambiguation, diff=medium)
- **id=128** `key-hygiene-v0-v1-cross-version` (stage=hallucination-resistance, tier=disambiguation, diff=medium)
- **id=129** `key-hygiene-custom-table-runtime-only` (stage=hallucination-resistance, tier=schema-introspection, diff=medium)
- **id=130** `key-hygiene-discovery-before-fetch` (stage=pipeline-usage, tier=disambiguation, diff=easy)
- **id=14** `merge-key-trodes-position` (stage=pipeline-usage, tier=merge-key-discovery, diff=medium)
- **id=15** `merge-key-lfp-default` (stage=pipeline-usage, tier=merge-key-discovery, diff=medium)
- **id=16** `merge-key-decoding-clusterless` (stage=pipeline-usage, tier=merge-key-discovery, diff=medium)
- **id=35** `merge-empty-list-ambiguity` (stage=runtime-debugging, tier=merge-table-gotchas, diff=medium)
- **id=49** `merge-silent-wrong-count` (stage=runtime-debugging, tier=merge-table-gotchas, diff=medium)
- **id=50** `merge-method-misattribution` (stage=common-mistakes, tier=merge-table-gotchas, diff=easy)
- **id=51** `is-this-a-merge-lookalike` (stage=common-mistakes, tier=merge-table-gotchas, diff=easy)

### Batch 2 — Hallucination resistance + common mistakes + framework concepts

- **id=21** `adversarial-hallucination-resistance` (stage=hallucination-resistance, tier=adversarial, diff=easy)
- **id=78** `abstain-session-samplingrate` (stage=hallucination-resistance, tier=adversarial, diff=medium)
- **id=79** `abstain-spyglassmixin-get-pk` (stage=hallucination-resistance, tier=adversarial, diff=easy)
- **id=80** `abstain-ripple-direct-dependency` (stage=hallucination-resistance, tier=adversarial, diff=medium)
- **id=81** `abstain-v1-naming-extrapolation` (stage=hallucination-resistance, tier=adversarial, diff=medium)
- **id=115** `adversarial-monkeypatch-make` (stage=hallucination-resistance, tier=adversarial, diff=hard)
- **id=122** `hallucination-fetch-nwb-single` (stage=hallucination-resistance, tier=adversarial, diff=easy)
- **id=123** `hallucination-spyglass-compact` (stage=hallucination-resistance, tier=adversarial, diff=medium)
- **id=5** `merge-delete-classmethod-discard` (stage=common-mistakes, tier=baseline, diff=medium)
- **id=25** `adversarial-too-loose-fetch1-pressure` (stage=common-mistakes, tier=adversarial, diff=medium)
- **id=30** `adversarial-copy-paste-params-blind` (stage=common-mistakes, tier=parameter-semantics, diff=medium)
- **id=7** `framework-concepts-merge-tables` (stage=framework-concepts, tier=table-classification, diff=medium)
- **id=73** `schema-pk-electrode` (stage=framework-concepts, tier=schema-introspection, diff=easy)
- **id=74** `schema-pk-firfilterparameters` (stage=framework-concepts, tier=schema-introspection, diff=easy)
- **id=75** `schema-dep-probe-electrode` (stage=framework-concepts, tier=schema-introspection, diff=easy)
- **id=76** `schema-dep-lfp-filter` (stage=framework-concepts, tier=schema-introspection, diff=easy)
- **id=77** `schema-part-tables-probe` (stage=framework-concepts, tier=schema-introspection, diff=easy)
- **id=96** `dependency-downstream-decoding-output` (stage=framework-concepts, tier=dependency-tracing, diff=hard)
- **id=97** `dependency-abstract-upstream` (stage=framework-concepts, tier=dependency-tracing, diff=medium)
- **id=109** `group-tables-concept` (stage=framework-concepts, tier=table-classification, diff=medium)

### Batch 3 — Pipeline usage round 1

- **id=6** `run-lfp-v1-pipeline` (stage=pipeline-usage, tier=baseline, diff=medium)
- **id=9** `atomic-fetch-session-row` (stage=pipeline-usage, tier=atomic-read, diff=easy)
- **id=10** `atomic-fetch-session-attributes` (stage=pipeline-usage, tier=atomic-read, diff=easy)
- **id=11** `atomic-list-intervals-for-session` (stage=pipeline-usage, tier=atomic-read, diff=easy)
- **id=12** `atomic-count-electrodes` (stage=pipeline-usage, tier=atomic-read, diff=easy)
- **id=13** `atomic-trodes-position-dataframe` (stage=pipeline-usage, tier=atomic-read, diff=medium)
- **id=17** `join-sessions-with-ripples-and-decoding` (stage=pipeline-usage, tier=joins, diff=medium)
- **id=18** `join-sessions-trodes-but-no-dlc` (stage=pipeline-usage, tier=joins, diff=medium)
- **id=19** `count-tetrodes-per-session` (stage=pipeline-usage, tier=joins, diff=easy)
- **id=26** `compound-full-session-pipeline` (stage=pipeline-usage, tier=compound, diff=hard)
- **id=28** `brain-region-for-curated-sorting` (stage=pipeline-usage, tier=joins, diff=medium)
- **id=29** `brain-region-for-lfp-electrode` (stage=pipeline-usage, tier=joins, diff=medium)
- **id=62** `disamb-trodes-vs-dlc` (stage=pipeline-usage, tier=disambiguation, diff=medium)
- **id=63** `disamb-lfpselection-vs-electrodegroup` (stage=pipeline-usage, tier=disambiguation, diff=medium)
- **id=64** `disamb-spikesortingv0-vs-v1` (stage=pipeline-usage, tier=disambiguation, diff=easy)
- **id=67** `counterfactual-ripple-electrode-set` (stage=pipeline-usage, tier=counterfactual, diff=hard)
- **id=68** `counterfactual-two-users-empty` (stage=pipeline-usage, tier=counterfactual, diff=hard)
- **id=69** `workflow-next-after-spikesortingselection` (stage=pipeline-usage, tier=workflow-position, diff=medium)
- **id=70** `workflow-next-after-dlcmodeltraining` (stage=pipeline-usage, tier=workflow-position, diff=hard)
- **id=71** `dep-trace-decoding-output` (stage=pipeline-usage, tier=dependency-tracing, diff=hard)

### Batch 4 — Pipeline usage round 2

- **id=72** `dep-trace-lfpbandv1` (stage=pipeline-usage, tier=dependency-tracing, diff=hard)
- **id=85** `recover-parameter-edit-in-place` (stage=pipeline-usage, tier=workflow-recovery, diff=hard)
- **id=87** `counterfactual-trodes-pos-params-swap` (stage=pipeline-usage, tier=counterfactual, diff=hard)
- **id=89** `restrict-by-interval-name-no-star` (stage=pipeline-usage, tier=joins, diff=medium)
- **id=90** `usage-after-lfpselection` (stage=pipeline-usage, tier=table-usage, diff=easy)
- **id=91** `usage-after-trodes-pos-selection` (stage=pipeline-usage, tier=table-usage, diff=easy)
- **id=92** `usage-after-positionoutput-row` (stage=pipeline-usage, tier=table-usage, diff=easy)
- **id=93** `usage-after-lfpbandv1-row` (stage=pipeline-usage, tier=table-usage, diff=easy)
- **id=94** `usage-pick-target-sampling-rate` (stage=pipeline-usage, tier=table-usage, diff=easy)
- **id=95** `join-dependent-attr-refusal` (stage=pipeline-usage, tier=joins, diff=hard)
- **id=98** `hidden-prereq-ripple-populate` (stage=pipeline-usage, tier=dependency-tracing, diff=medium)
- **id=99** `hidden-prereq-decoding-populate` (stage=pipeline-usage, tier=dependency-tracing, diff=hard)
- **id=100** `workflow-position-post-sort-clusterless-decode` (stage=pipeline-usage, tier=workflow-position, diff=medium)
- **id=102** `session-recording-devices` (stage=pipeline-usage, tier=joins, diff=medium)
- **id=103** `session-subject-owner` (stage=pipeline-usage, tier=joins, diff=medium)
- **id=104** `probe-per-electrode-group` (stage=pipeline-usage, tier=atomic-read, diff=easy)
- **id=105** `camera-devices-lookup` (stage=pipeline-usage, tier=atomic-read, diff=easy)
- **id=106** `compound-pfc-wtrack` (stage=pipeline-usage, tier=compound, diff=hard)
- **id=108** `sorted-spikes-group-hippocampal` (stage=pipeline-usage, tier=disambiguation, diff=medium)

### Batch 5 — Pipeline usage round 3 + parameter understanding

- **id=57** `param-target-sampling-rate` (stage=parameter-understanding, tier=parameter-semantics, diff=hard)
- **id=58** `param-speed-threshold-ripple` (stage=parameter-understanding, tier=parameter-semantics, diff=medium)
- **id=59** `param-encoding-vs-decoding-interval` (stage=parameter-understanding, tier=parameter-semantics, diff=medium)
- **id=60** `param-trodes-smoothing` (stage=parameter-understanding, tier=parameter-semantics, diff=hard)
- **id=61** `param-sort-group-by-electrode-group` (stage=parameter-understanding, tier=parameter-semantics, diff=hard)
- **id=116** `counterfactual-ripple-threshold` (stage=parameter-understanding, tier=counterfactual, diff=hard)
- **id=117** `counterfactual-sort-interval-change` (stage=parameter-understanding, tier=counterfactual, diff=hard)
- **id=118** `counterfactual-decoding-bin-size` (stage=parameter-understanding, tier=counterfactual, diff=hard)

### Batch 6 — Runtime debugging

- **id=3** `fetch1-cardinality-error` (stage=runtime-debugging, tier=baseline, diff=easy)
- **id=4** `populate-fails-halfway-through` (stage=runtime-debugging, tier=baseline, diff=hard)
- **id=27** `compound-decoding-populate-fail-triage` (stage=runtime-debugging, tier=compound, diff=hard)
- **id=31** `env-spikeinterface-drift` (stage=runtime-debugging, tier=environment-triage, diff=medium)
- **id=36** `runtime-populate-non-pk-dict` (stage=runtime-debugging, tier=runtime-errors, diff=easy)
- **id=37** `runtime-dlc-positionintervalmap` (stage=runtime-debugging, tier=runtime-errors, diff=hard)
- **id=38** `runtime-decoding-oom` (stage=runtime-debugging, tier=runtime-errors, diff=medium)
- **id=39** `runtime-clusterless-contact-unique` (stage=runtime-debugging, tier=runtime-errors, diff=medium)
- **id=43** `runtime-fk-ancestor-missing` (stage=runtime-debugging, tier=runtime-errors, diff=medium)
- **id=44** `runtime-populate-all-common-silent` (stage=runtime-debugging, tier=runtime-errors, diff=medium)
- **id=48** `runtime-positiongroup-variable-mismatch` (stage=runtime-debugging, tier=runtime-errors, diff=hard)
- **id=52** `runtime-join-dependent-attribute` (stage=runtime-debugging, tier=runtime-errors, diff=medium)
- **id=65** `resource-first-ref-fetch1` (stage=runtime-debugging, tier=resource-selection, diff=easy)
- **id=82** `resource-first-ref-populate-all-common` (stage=runtime-debugging, tier=resource-selection, diff=easy)
- **id=84** `recover-partial-populate-common` (stage=runtime-debugging, tier=workflow-recovery, diff=hard)
- **id=86** `counterfactual-decoding-noise-divergence` (stage=runtime-debugging, tier=counterfactual, diff=hard)
- **id=101** `recovery-populate-partial-electrodes` (stage=runtime-debugging, tier=workflow-recovery, diff=hard)
- **id=119** `permission-error-analysis-nwbfile-write` (stage=runtime-debugging, tier=runtime-errors, diff=medium)
- **id=120** `slow-fetch-db-lock` (stage=runtime-debugging, tier=runtime-errors, diff=medium)

### Batch 7 — Setup / ingestion / pipeline-authoring / destructive / table-understanding / non-activation

- **id=1** `fresh-install-remote-lab-db` (stage=setup, tier=baseline, diff=medium)
- **id=2** `ingest-new-nwb-file` (stage=ingestion, tier=baseline, diff=medium)
- **id=8** `author-custom-pipeline-off-lfp` (stage=pipeline-authoring, tier=baseline, diff=hard)
- **id=20** `adversarial-non-activation-pynwb` (stage=non-activation, tier=adversarial, diff=easy)
- **id=22** `adversarial-password-exposure` (stage=non-activation, tier=adversarial, diff=easy)
- **id=23** `adversarial-destructive-skip-dry-run` (stage=destructive-operations, tier=adversarial, diff=medium)
- **id=24** `adversarial-skip-cautious-delete` (stage=destructive-operations, tier=adversarial, diff=medium)
- **id=32** `ingest-channel-slice-parents` (stage=ingestion, tier=post-ingest-validation, diff=hard)
- **id=33** `ingest-task-epoch-drop` (stage=ingestion, tier=post-ingest-validation, diff=medium)
- **id=34** `ingest-device-conflict` (stage=ingestion, tier=post-ingest-validation, diff=medium)
- **id=40** `config-stores-cross-machine` (stage=setup, tier=config-troubleshooting, diff=medium)
- **id=41** `config-key-error-after-pull` (stage=setup, tier=config-troubleshooting, diff=medium)
- **id=42** `destruct-super-delete-no-cleanup` (stage=destructive-operations, tier=adversarial, diff=hard)
- **id=45** `config-permission-triage` (stage=setup, tier=config-troubleshooting, diff=hard)
- **id=46** `env-editable-install-drift` (stage=setup, tier=environment-triage, diff=medium)
- **id=47** `env-conda-pip-drift` (stage=setup, tier=environment-triage, diff=medium)
- **id=53** `classify-lfpselection` (stage=table-understanding, tier=table-classification, diff=easy)
- **id=54** `classify-trodesposparams-vs-selection` (stage=table-understanding, tier=table-classification, diff=medium)
- **id=55** `classify-positionoutput-merge` (stage=table-understanding, tier=table-classification, diff=medium)
- **id=56** `classify-lfpband-role` (stage=table-understanding, tier=table-classification, diff=easy)
- **id=66** `resource-first-ref-merge-delete` (stage=destructive-operations, tier=resource-selection, diff=easy)
- **id=83** `resource-first-ref-custom-pipeline-author` (stage=pipeline-authoring, tier=resource-selection, diff=easy)
- **id=88** `ambiguity-delete-decoding-results` (stage=destructive-operations, tier=disambiguation, diff=medium)
- **id=107** `compound-sorted-spikes-across-sort-groups` (stage=pipeline-authoring, tier=compound, diff=hard)
- **id=110** `custom-analysis-table-shape` (stage=pipeline-authoring, tier=atomic-read, diff=medium)
- **id=111** `custom-table-multiple-nwbs-blob-pushback` (stage=pipeline-authoring, tier=parameter-semantics, diff=hard)
- **id=112** `adversarial-edit-dlcposv1` (stage=pipeline-authoring, tier=adversarial, diff=medium)
- **id=113** `adversarial-update1-downstream-populated` (stage=destructive-operations, tier=adversarial, diff=medium)
- **id=114** `adversarial-cross-corr-blob-column` (stage=pipeline-authoring, tier=adversarial, diff=hard)
- **id=121** `editable-install-drift-after-pull` (stage=setup, tier=environment-triage, diff=medium)
