# Rules

This document describes the current rules that actually drive coaching output in version 1.

It is a rules handout first, not a product spec and not a medical document.

## What The System Looks At

The current rules use these inputs:

- food logs from conversation ingest
- hunger logs from conversation ingest
- latest body weight
- recent Oura daily metrics
- goal config
- anonymized baseline health markers from the imported report

The current output surfaces are:

- daily review
- daily insights
- real-time advice

## Current Baseline Markers That Affect Output

The current logic only uses these baseline markers as active constraints:

- `high_uric_acid`
- `high_total_cholesterol`
- `sinus_bradycardia`

Other imported markers are stored and available, but they do not yet change coaching output directly.

## Rule Priority

The current system is rules-first and priority-based.

In practice, the order is:

1. recent recovery problems
2. repeated hunger signals
3. baseline constraints
4. logging gaps
5. generic fallback guidance

That means a low-readiness day can override a more generic baseline note, and repeated hunger can override a simple tracking reminder.

## Daily Review Rules

The daily review generates three parts:

- yesterday's key issue
- best adjustment for today
- realism check

### Key Issue

The current priority order is:

1. If the most recent Oura `readiness_score` is below `70`, the key issue becomes low recovery.
2. Else if the recent hunger window has at least `2` hunger signals, the key issue becomes that the current plan is likely too aggressive.
3. Else if baseline includes `high_uric_acid`, the key issue becomes avoiding drift into high-purine compensation.
4. Else if baseline includes `high_total_cholesterol`, the key issue becomes long-term food quality.
5. Else if there are no food logs for the review date, the key issue becomes insufficient tracking.
6. Else the fallback issue is that eating decisions still need tighter structure.

### Best Adjustment

The current priority order is:

1. If the recent hunger window has at least `2` hunger signals, recommend front-loading protein earlier in the day.
2. Else if baseline includes `high_uric_acid`, recommend stable lower-purine meals by default.
3. Else if baseline includes `high_total_cholesterol`, recommend reducing processed and high-saturated-fat choices rather than chasing short-term restriction.
4. Else if there are no food logs for the review date, recommend restoring a usable data trail by logging meals and hunger.
5. Else if `late_night_snack_limit <= 2`, recommend bounding late-night eating in advance.
6. Else repeat the easiest-to-execute parts of the prior day.

### Realism Check

The current priority order is:

1. If the most recent Oura `readiness_score` is below `70`, realism note says the target should be softer.
2. Else if the recent hunger window has at least `2` hunger signals, realism note says the plan should bias toward controlled flexibility.
3. Else if baseline includes `sinus_bradycardia`, realism note says the pace should stay conservative and recovery-aware.
4. Else the fallback note says the recommendation is realistic if the decision happens before hunger gets strong.

## Daily Insights Rules

The insight system builds daily features, then scores hypotheses. Only hypotheses with score greater than `0` are kept.

### Recovery Driven Appetite

Label: `睡眠/恢复驱动食欲风险`

Scoring:

- `+0.35` if `readiness_score < 70`
- `+0.30` if `total_sleep_minutes < 390`
- up to `+0.25` from hunger count

Purpose:

- capture days where poor recovery is a likely appetite trigger

### Plan Too Aggressive

Label: `当前计划过硬风险`

Scoring:

- `+0.45` if `hunger_count >= 2`
- `+0.35` if there is at least one high-hunger signal

Purpose:

- capture that the plan may be harder than current execution capacity

### Tracking Gap

Label: `记录缺口`

Scoring:

- `0.5` if there are no food logs
- `0.7` if there are no food logs and there are hunger signals without meal context

Purpose:

- highlight that the system lacks enough context to infer causes

### Late Night Pattern

Label: `晚间加餐模式`

Scoring:

- `0.7` if any meal slot is `late_night`

Purpose:

- identify late-night eating as a repeatable pattern

### Meal Structure Risk

Label: `餐次结构风险`

Scoring:

- `0.45` if there are hunger signals and no breakfast log

Purpose:

- flag likely meal-structure problems before blaming willpower

### Urate Constraint

Label: `高尿酸约束`

Scoring:

- `0.6` if baseline includes `high_uric_acid`

Purpose:

- keep downstream suggestions away from high-purine compensation patterns

### Lipid Constraint

Label: `血脂约束`

Scoring:

- `0.55` if baseline includes `high_total_cholesterol`

Purpose:

- keep downstream suggestions attentive to fat quality and processed-food load

## Real-Time Advice Rules

The advice endpoint starts from a default bounded-permission answer and then tightens it with recent behavior, weight, and baseline constraints.

### Base Advice

Default output:

- conclusion: `可以吃，但要有边界。`
- why: no strong signal says this needs to be fully forbidden
- alternative: make it a small portion and pair it with a meal or higher-protein food

### Recovery Or Hunger Escalation

If either of these is true:

- latest recovery is low
- recent hunger window has at least `2` entries

Then advice changes to:

- conclusion: `可以吃，但不建议放任式吃。`
- why: unstable recovery or hunger makes compensatory eating more likely
- alternative: pre-commit a small portion, or delay for `20` minutes if it is likely emotional craving

### Weight Guardrail

If latest weight is above the configured target range max:

- append a warning that current weight is already above the target upper bound

### Baseline Constraint Additions

If baseline includes `high_uric_acid`:

- append a warning to avoid drifting into a high-purine compensation route

If baseline includes `high_total_cholesterol`:

- append a warning to pay more attention to fat sources and long-term structure

If baseline includes `sinus_bradycardia`:

- append a more conservative alternative that avoids stacking compensation eating and aggressive exercise on the same day

### Advice Context Storage

Each advice record currently stores:

- recent hunger count
- recent Oura day count
- latest weight
- `baseline_marker_keys`

This is so future calibration can know which baseline constraints were active when advice was generated.

## What Is Not Implemented Yet

These are not part of the current rule engine:

- severity-weighted marker logic
- per-food purine or fat-source classification
- time decay for older reports
- dynamic rule weighting from advice-outcome feedback
- direct use of most baseline markers in coaching output
- diagnosis or clinical interpretation

## Code Entry Points

Current rule entry points:

- `generate_review()`: `/Users/cjyyyyy/Documents/Playground/local-health-assistant/src/local_health_assistant/service.py`
- `respond_to_advice()`: `/Users/cjyyyyy/Documents/Playground/local-health-assistant/src/local_health_assistant/service.py`
- `_determine_key_issue()`: `/Users/cjyyyyy/Documents/Playground/local-health-assistant/src/local_health_assistant/service.py`
- `_determine_adjustment()`: `/Users/cjyyyyy/Documents/Playground/local-health-assistant/src/local_health_assistant/service.py`
- `_determine_realism_note()`: `/Users/cjyyyyy/Documents/Playground/local-health-assistant/src/local_health_assistant/service.py`
- `generate_daily_insights()`: `/Users/cjyyyyy/Documents/Playground/local-health-assistant/src/local_health_assistant/insights.py`
- `build_daily_features()`: `/Users/cjyyyyy/Documents/Playground/local-health-assistant/src/local_health_assistant/insights.py`
- `score_*()` functions: `/Users/cjyyyyy/Documents/Playground/local-health-assistant/src/local_health_assistant/insights.py`

## Read This As A Constraint System

The current rules do not try to diagnose.

They do three narrower things:

- explain likely behavior drivers
- keep advice within safer personal constraints
- turn baseline findings into practical guardrails for everyday decisions
