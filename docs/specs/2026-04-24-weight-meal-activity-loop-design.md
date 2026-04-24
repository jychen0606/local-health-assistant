# Weight, Meal, And Activity Loop Design

## Goal

Extend the current local-health-assistant from a generic daily-review system into a more behavior-timed loop:

- morning weight entry can trigger abnormal-weight review
- post-meal logging can trigger meal evaluation and next-meal advice
- Oura activity updates can enter the judgment loop through periodic sync

The first version should stay local, deterministic, and low-friction. It should not depend on active push messaging.

## Scope

This design covers three additions:

1. weight-triggered abnormal review
2. post-meal evaluation and next-meal suggestion
3. hourly Oura activity sync entering the judgment context

This design explicitly does not include:

- direct image understanding inside this project
- active notifications to Telegram, iMessage, or other channels
- calorie or nutrient precision analysis
- diagnosis or clinical interpretation

## Product Shape

The recommended shape is a mixed real-time plus scheduled model:

- weight entry is evaluated immediately
- meal logging is evaluated immediately
- sleep/readiness sync remains a morning scheduled task
- activity sync runs hourly
- all generated results are stored locally
- no active push is sent in version 1

This keeps the system aligned with the user's actual behavior while avoiding the complexity of a message-delivery layer.

## Part 1: Weight-Triggered Abnormal Review

### Trigger

When a new morning body-weight record is ingested, the system should evaluate whether the weight represents an abnormal day-level deviation.

### Reference Weight

The reference should be:

1. the mean of the previous three available morning weights, if enough data exists
2. otherwise the immediately previous weight record

### Abnormality Rule

Compute:

- `delta_kg = today_weight - reference_weight`

A weight is treated as abnormal if:

- `abs(delta_kg) >= 1.0`

The first version does not attempt to classify "good abnormal" versus "bad abnormal". It only treats the value as an abnormal fluctuation requiring context.

### Abnormal Review Inputs

If the weight is abnormal, generate a targeted review using:

- yesterday's Oura sleep and readiness
- yesterday's Oura activity context
- yesterday's food and hunger logs
- late-night eating patterns if present
- recent three-to-seven-day weight trend
- active baseline constraints

### Output

Store a structured abnormal-weight review with:

- `is_abnormal`
- `delta_kg`
- `reference_weight_kg`
- `suspected_drivers`
- `review_text`
- `recommended_action`

If the weight is not abnormal, only the weight record is stored and no abnormal review is generated.

## Part 2: Post-Meal Evaluation And Next-Meal Suggestion

### Input Model

The project continues to use text as the internal input format.

Meal records can arrive from:

1. direct user text
2. ChatGPT-generated text after image understanding
3. ChatGPT-generated text after ingredient-label understanding

The project itself does not perform image understanding in version 1.

### Input Expectations

The incoming text should describe:

- meal slot if known
- what was eaten
- drinks or desserts if relevant
- optional packaged-food or ingredient-label notes

If a label was provided to ChatGPT beforehand, the text may also include:

- obvious added sugar or syrup signals
- obvious high-fat or highly processed signals
- a short caution note

### Immediate Output

After the meal is logged, the system should immediately generate two outputs:

1. a short evaluation of the meal
2. a suggestion for the next meal only

The system should not respond with a full-day nutrition plan.

### Meal Evaluation

The evaluation should stay short and practical:

- overall assessment
- biggest issue
- one redeeming strength if present

The goal is not nutritional completeness. The goal is to convert a meal into useful next-step context.

### Next-Meal Suggestion Inputs

The next-meal suggestion should use:

- current goals
- baseline constraints
- last seven days of meal structure
- what has already been eaten today
- recent sleep/readiness
- recent weight trend
- recent advice-gap behavior

### First-Version Boundaries

The first version should not:

- estimate calories precisely
- estimate macronutrients precisely
- infer nutrients from uncertain imagery

It should focus on:

- food type and structure
- processed-food cues
- dessert/drink stacking
- next-meal correction that is realistic

## Part 3: Oura Activity Sync

### Sync Model

The system should keep the existing morning sync for yesterday's sleep/readiness.

In addition, it should run an hourly sync for same-day activity context.

### Priority Data

The first version should prioritize:

- daily activity summaries
- workout summaries

This is enough to improve the decision loop without over-expanding scope.

### New Activity Detection

Each hourly run should:

1. fetch same-day activity/workout context
2. compare against the most recent stored snapshot
3. store new activity information if something changed materially

The first version does not need a user-facing "I have already counted it" push notification.

### How Activity Enters Judgment

Activity should influence:

1. abnormal-weight review
2. next-meal suggestion
3. daily review and insights

The interpretation should stay conservative. Activity is part of the context, not a permission slip for uncontrolled eating and not an excuse for compensatory restriction.

## Storage Changes

The implementation will likely need new structured data for:

- abnormal weight events/reviews
- meal evaluations
- next-meal suggestions
- incremental activity sync state

The exact table design can be finalized during implementation planning, but the boundary should be:

- facts in SQLite
- readable review artifacts in Markdown when useful
- raw Oura snapshots in JSON

## API Changes

Expected additions or adjustments:

- weight-ingest path should be able to trigger abnormal review generation
- meal-ingest path should be able to return meal evaluation plus next-meal advice
- morning job should continue to exist
- hourly activity job should be added as a separate scheduled flow

No external message-delivery endpoint is required for version 1.

## Scheduling

Recommended first-version schedule:

- `08:30`: pull yesterday's sleep/readiness, then generate review and insights
- every hour: pull same-day activity/workout context

No active push should be emitted. Results are only stored and become visible the next time the user interacts.

## Decision Principles

The system should optimize for:

- practical execution
- explainable triggers
- low scope creep
- low false certainty

The system should avoid:

- pretending uncertain image guesses are structured facts
- giving a full nutrition lecture every meal
- treating single-day weight shifts as fat gain or fat loss by default

## Acceptance Criteria

This design is successful if:

- a morning weight entry can trigger an abnormal review when the deviation is at least 1 kg
- a meal log can immediately produce a meal evaluation and next-meal suggestion
- hourly activity sync updates local context without requiring active push
- review and advice can use the new activity and weight-event context
- the whole loop still works without a notification channel
