# Codex Batch 6 Grade

This is a separate Codex-side grading artifact. It intentionally does not use
`benchmark.json` or `grader_summary.md`, which are reserved for the benchmark
runner / other agent.

## Strict Assertion Score

| condition | evals full pass | expectation pass rate | expectations | tokens / run | duration / run |
| --- | ---: | ---: | ---: | ---: | ---: |
| with_skill | 19/19 | 100.0% | 184/184 | 48,533 | 89.2s |
| baseline | 17/19 | 98.4% | 181/184 | 28,250 | 68.0s |

Delta: with_skill +2 full-pass evals and +1.6 percentage points.

## Baseline Misses

- **eval-082 `resource-first-ref-populate-all-common`**: real baseline miss
  for skill routing. It gives a strong substantive `populate_all_common`
  diagnostic, including logger output, return values, `InsertError`, and no
  invented scripts. But it does not name `populate_all_common_debugging.md` or
  explain why that reference beats `runtime_debugging.md`.
- **eval-084 `recover-partial-populate-common`**: real baseline miss for
  skill routing. It gives a conservative recovery plan and warns against
  deletion / blind reruns, but it does not name `populate_all_common_debugging.md`.

## Interpretation

Batch 6 shows a smaller but real strict-score skill lift. The main lift is not
generic runtime reasoning: the baseline handled most runtime-debugging cases
well. The skill advantage is in routing to the specialized
`populate_all_common_debugging.md` reference and preserving exact
Spyglass-specific recovery surfaces.

The eval layer now avoids the brittle raw forbidden-substring checks that
punished correct-in-context negations in eval-043 and eval-082. The remaining
baseline misses are substantive skill-routing misses, not artifacts of quoted
or negated bad recommendations.
