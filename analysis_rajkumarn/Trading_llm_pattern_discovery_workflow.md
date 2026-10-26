# LLM-Assisted Indicator Pattern Discovery and Validation

## Objective

Use an LLM to propose explicit indicator conditions from a small set of
NIFTY turning-point zones, use Python to verify the condition was
expressed correctly, then test whether it generalizes to unseen zones
and non-zone periods.

The LLM is a hypothesis generator; Python is the deterministic
evaluator. A condition matching a sample is not automatically a valuable
or predictive condition.

## Workflow

### 1. Prepare a discovery sample

-   Select around 10 representative zones.
-   Supply consistent windows, zone IDs, timestamps, and features
    available at the intended prediction time.
-   Features may include indicator values, timeframe values,
    lag/sequence values, differences, slopes, normalized distances, and
    candidate behaviours.
-   Do not expose future values as predictor inputs. Future data may
    define the outcome label only.

Ten zones can help generate hypotheses, but are not enough to establish
reliability.

### 2. Ask the LLM for explicit candidate conditions

For every candidate, request: - Plain-language description. - Exact
feature names, operators, thresholds, and time relationships. - Zone IDs
it believes match and do not match. - Assumptions, missing-value
handling, and rationale.

Example only: `MACD_5m` is between -2.5 and -1.5 while its recent slope
is positive. The threshold must be data-derived, not assumed to be a
trading rule.

Require mathematical definitions for words such as "weakening,"
"shrinking," or "confirmation."

### 3. Ask the LLM to write Python verification code

The code should return: - Match/non-match result for each row or zone. -
Matching and non-matching zone IDs. - Feature values used for each
decision. - Which clauses passed or failed.

Run the code and inspect its output. Do not rely on the LLM's verbal
claim alone.

### 4. Verify that the condition was conveyed correctly

Suppose the LLM claims the condition matches Zones 1, 3, 5, and 6. Run
the Python condition on the exact discovery sample and compare its match
list.

-   If Python returns the same IDs, the expression agrees with the LLM's
    claim on that sample.
-   If not, inspect feature names, inequalities, timestamps, missing
    values, and interpretation; correct and rerun.
-   Save the formal expression and test results for reproducibility.

**This checks translation correctness, not predictive value.**

### 5. Apply the condition to unseen zones

Once verified, test the condition on zones that were not shown to the
LLM. Measure event coverage/recall, consistency across dates and market
regimes, and lead time before the target event.

If the LLM has seen or repeatedly refined the rule against all zones,
those zones are part of discovery---not independent validation.

### 6. Test non-zone periods

A condition may occur around many target zones and also occur frequently
when no event is approaching. Evaluate eligible non-zone prediction
times.

Measure: - Precision: fraction of condition triggers followed by the
target event within the defined horizon. - Recall/coverage: fraction of
target events preceded by the condition. - False-positive rate. - Lift
over baseline event rate. - Support across distinct events and dates. -
Lead time and chronological stability.

Avoid treating thousands of adjacent rows as independent examples.

### 7. Keep, refine, or reject

Keep for further study only if the rule is unambiguous, reproducible,
supported by multiple distinct events, discriminates target zones from
non-zone periods, generalizes to later dates, has useful lead time,
avoids leakage, and adds value beyond redundant rules.

Do not rank by raw zone matches alone. A rule matching 80/100 events but
also firing in 75% of non-event periods may be less useful than a rule
matching 35/100 but firing in only 8% of non-event periods. Compare
precision, recall, event prevalence, stability, and intended use.

## Recommended chronological split

-   **Discovery:** LLM proposes conditions.
-   **Development/validation:** compare and refine candidates.
-   **Final holdout:** later dates kept untouched until the rules and
    thresholds are fixed.

Use date/event-level splits rather than random row splits because
adjacent windows overlap and are dependent. Consider a gap between
splits. With few zones, report uncertainty honestly.

## Responsibilities

**LLM:** propose candidate conditions, interpret temporal behaviour,
explain hypotheses, draft Python checks, suggest alternatives.

**Python:** calculate features, verify matches, score event and
non-event periods, run chronological validation, check
leakage/missingness, and produce reproducible reports.

The LLM must not be the final judge of statistical value.

## Candidate-condition record

Suggested fields: `condition_id`, `indicator_family`, `feature_names`,
`description`, `formal_expression`, `claimed_zone_ids`,
`python_match_zone_ids`, `translation_check_passed`,
`validation_support`, `precision`, `recall`, `false_positive_rate`,
`baseline_lift`, `lead_time`, `chronological_stability`,
`redundancy_group`, `decision`, `notes`.

## Summary

**LLM observes sample → proposes explicit condition → Python checks
claimed matches → test on unseen zones and non-zone periods →
chronological validation decides whether the condition merits further
consideration.**
