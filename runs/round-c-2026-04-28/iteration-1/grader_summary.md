# Iteration 1 grader summary

Graded 28 runs across 14 evals × {with_skill, without_skill}. Filled in only
the `behavioral_check` verdicts; substring assertions had already been graded
programmatically.

## Behavioral-check totals

- **with_skill:** 53 / 53 behavioral checks passed (0 failed).
- **without_skill:** 49 / 53 behavioral checks passed (4 failed).

The four baseline failures all come from a single eval (eval-130, see below).
Every other eval's baseline run satisfied every behavioral check this rubric
asks for.

## Patterns

- **Both conditions hit the merge-table fundamentals.** On the merge-key
  retrieval and merge-table-gotcha evals (014/015/016/035/049/050/051/126),
  with_skill and without_skill both consistently used `merge_get_part` as a
  classmethod, used `merge_restrict` for counting/filtering rather than a bare
  `&`, named all five merge masters when asked, and warned about the
  silent-no-op shape on merge masters. Differences were stylistic, not
  rubric-relevant.
- **Skill-specific tooling shows up only in with_skill.** The skill side
  routinely cites the bundled `code_graph.py describe` / `find-method` and
  `db_graph.py describe` CLIs, links to specific reference files
  (`merge_methods.md`, `lfp_pipeline.md`, `feedback_loops.md`,
  `ripple_pipeline.md`, etc.), and references "Common Mistake #N" by number.
  The baseline never names those tools or files. The rubric tolerates this:
  for verification checks I credited any sound runtime/source path
  (`heading.primary_key`, `dir(...)`, grepping `$SPYGLASS_SRC`) — none of those
  are skill-only.
- **with_skill is more conservative on under-specified prompts.** eval-130
  ("Give me code to fetch the LFP for my session") is the only prompt with no
  natural primary-key disambiguation in it. The skill answer treats it as
  under-specified, enumerates candidates, asks the user, and warns explicitly
  against the merge-master silent no-op. The baseline answer hands back a
  one-liner `(LFPV1 & {'nwb_file_name': ...}).fetch1_dataframe()` plus a
  bare-restriction `(LFPOutput & {...}).fetch1('KEY')`. That single eval
  accounts for all four baseline behavioral failures.

## Evals where without_skill scored worse

- **eval-130 (key-hygiene-discovery-before-fetch):** without_skill failed all
  four behavioral checks. The baseline hands the user the exact two
  anti-patterns the eval is designed to catch — partial-key `fetch1` on
  `LFPV1` and bare-restriction on the `LFPOutput` merge master. with_skill
  passed all four (discovery first, all four LFP PK fields named, merge_get_part
  for resolution, cardinality check before fetch1).

No other eval has the with_skill answer scoring worse than baseline; on every
other eval the two are tied at full behavioral-check pass.

## Close-call grading judgments

- **eval-129 without_skill, "states code_graph.py cannot see external
  tables" check.** The baseline doesn't name `code_graph.py`, but it does say
  "Don't search the upstream Spyglass repo for it ... any source-graph /
  repo-grep tool scoped to Spyglass will come up empty." I credited this as a
  pass because the rubric says to be fair to baseline on skill-only routing
  claims — the baseline articulates the underlying boundary (source tools
  scoped to Spyglass don't see lab packages) without naming the tool by name.
- **eval-129 without_skill, "recommends db_graph.py OR
  heading.primary_key OR source read."** The check is an OR-chain. Baseline
  doesn't mention `db_graph.py` (skill-only), but does recommend
  `heading.primary_key` and reading the lab-package source — both of which the
  rubric explicitly accepts. Pass.
- **eval-125 with_skill, forbidden-substring `RippleParameters &
  {"speed_threshold"`.** The substring is present (already failed
  programmatically). It appears only inside a "Why this won't work" example
  the response is arguing against, not as a recommendation, so the
  *behavioral* checks (which don't reproduce the substring rule) all still
  pass. Worth noting because the substring failure looks worse than the actual
  content does.
- **eval-127, "names missing PK fields explicitly."** Both responses list
  `RippleLFPSelection` and `pos_merge_id` as missing. The skill response is
  more explicit ("RippleLFPSelection's PK ... and pos_merge_id"), but the
  baseline's enumeration ("PK is the union of: 1. The PK of RippleLFPSelection
  ... 3. pos_merge_id") is equally specific. Pass for both.
