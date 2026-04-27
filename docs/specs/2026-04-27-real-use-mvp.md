# Real Use MVP

## Goal

Turn the local-health-assistant from a local API demo into a tool that can be used in daily life.

The real product is not the browser page. The browser page is only a debug panel. The real loop is:

1. the user records naturally in ChatGPT or WeChat
2. Codex or a future bridge forwards the record into the local service
3. the service stores facts, Oura context, baseline constraints, and generated advice
4. the service can explain what it currently understands and what it still needs
5. the user gets immediate meal/weight feedback and a daily review

The first useful version should stay deterministic, local-first, and simple enough to run every day.

## Primary Outcome

The primary outcome is weight maintenance or slow weight reduction.

The system should not treat weight change as a standalone goal. It should first help the user understand:

- when eating is needed because of activity, hunger, or recovery
- when eating is likely compensatory, late-night, or emotionally driven
- when exercise creates a real need to replenish
- when exercise is being used as a reason for over-restriction or overcompensation
- how baseline health markers should constrain advice

Weight maintenance or reduction is the result of better timing, better interpretation, and fewer compensation loops.

## Priority Order

When advice conflicts, use this priority order:

1. maintain or slowly reduce body weight
2. reduce compensatory eating and late-night loss of control
3. avoid overcompensation around exercise and poor recovery
4. improve meal structure and food quality
5. optimize secondary goals only after the above are stable

The system should not give advice that improves a lower-priority goal while damaging a higher-priority one.

## Real Input Channel

The MVP input channel is manual natural-language forwarding through ChatGPT or WeChat.

The user can write records such as:

```text
早上体重55.0
早餐吃了两个蛋和牛奶
下午打网球一小时
晚上很饿，想吃甜的
```

Codex can forward these records into the local API during the early MVP. A later version can automate the bridge, but the first version should not be blocked on Telegram, iMessage, WeChat automation, or a polished web app.

The browser page remains useful for:

- checking local service status
- testing ingest
- viewing current onboarding and baseline state
- manually debugging API behavior

It is not the main user experience.

## Minimal Daily User Actions

The user should only need to provide a few lightweight records:

- morning weight, when available
- meals, especially meals that include dessert, drinks, late-night eating, or unusual portions
- hunger or craving events
- exercise sessions that matter for appetite or recovery
- short follow-up on whether advice was followed

The user should not be asked to manually calculate:

- protein targets
- calorie ranges
- target-weight upper and lower bounds
- recovery corrections
- health-marker constraints

Those values should be derived by the service from profile, baseline, Oura, and observed behavior.

## Natural-Language Record Protocol

The service should support natural language plus light keywords.

Recommended patterns:

```text
早上体重 55.0kg
早餐：两个鸡蛋，牛奶，咖啡
午餐：牛肉饭，青菜
下午很饿，想吃甜的
运动：网球 60 分钟
晚餐后还是想吃零食
```

The parser should continue to accept looser inputs, but the service should get better at these patterns first.

If a record cannot be confidently parsed, the service should still store the original message as a conversation event. Losing data is worse than storing an incomplete structured fact.

## Oura Status

Oura has already been integrated at the code level:

- OAuth flow
- token storage
- manual daily sync
- activity sync
- morning briefing orchestration
- normalized sleep, readiness, and activity metrics

The remaining MVP work is not "connect Oura" from scratch. It is to verify and operationalize Oura:

- whether a valid token exists locally
- whether the latest sync succeeds
- what the latest synced dates are
- whether sleep, readiness, activity, and workout data are present
- whether those metrics are actually used in current context and advice

Oura should be part of the context health check.

## Core Missing Backend Capability

The next backend milestone is a system-understanding endpoint:

```text
GET /health/context
```

This endpoint should answer:

- what the service already knows
- what data is missing
- how current strategy was derived
- what baseline constraints are active
- what Oura data is available
- what recent food, weight, hunger, activity, and advice-outcome signals exist
- what the next useful question is

This endpoint is more important than more browser UI because it becomes the shared decision layer for the browser page, ChatGPT forwarding, future message bridges, morning jobs, and advice endpoints.

## Proposed Context Response

The first version can be deterministic:

```json
{
  "known": {
    "onboarding_profile": true,
    "baseline_report": true,
    "oura_token": true,
    "latest_oura_sync_date": "2026-04-26",
    "recent_food_logs": 5,
    "recent_weight_logs": 4,
    "recent_hunger_logs": 2
  },
  "current_strategy": {
    "phase": "fat_loss",
    "target_weight_kg": 53.0,
    "target_observation_range_kg": [52.2, 53.8],
    "nutrition_strategy": "Use stable meals and avoid extreme restriction or high-purine compensation.",
    "activity_strategy": "Treat exercise as context for replenishment and recovery, not as permission for uncontrolled eating.",
    "risk_constraints": [
      "high_uric_acid",
      "high_total_cholesterol",
      "high_waist_hip_ratio",
      "low_diastolic_blood_pressure"
    ]
  },
  "missing": [
    "3-7 consecutive morning weight records",
    "more complete meal logs",
    "recent advice outcome feedback"
  ],
  "next_question": "晚上想吃东西通常是在晚餐后多久出现？"
}
```

Exact field names can change during implementation, but the endpoint should stay focused on service state and next action.

## Daily Review MVP

The user and Codex agree on two core MVP situations:

1. immediate feedback after meals or weight entries
2. daily review, preferably morning review of yesterday

Daily review should use the context endpoint rather than recomputing scattered state independently.

The daily review should explain:

- yesterday's main issue
- today's most important adjustment
- whether the advice is realistic
- what evidence was used
- which baseline or Oura constraints mattered
- what data was missing

## Advice Moment MVP

When the user asks "can I eat this?" or reports a craving, the system should decide from context:

- Is this real hunger, recovery need, or planned replenishment?
- Is this likely late-night or compensatory eating?
- Was there meaningful exercise today?
- Is recovery weak?
- Does baseline suggest avoiding a specific compensation pattern?
- Would a smaller portion or different pairing be better?

The output should be bounded:

- clear yes/no/yes-but conclusion
- reason in 1-3 sentences
- realistic alternative
- what to record afterwards

## Implementation Steps

### Step 1: Build `GET /health/context`

Codex does:

- add response models
- gather onboarding, goals, baseline, Oura token/sync state, recent logs, and advice outcomes
- generate known/missing summaries
- generate current strategy
- generate next useful question

User does:

- review whether the context summary matches reality
- decide whether the next question is useful

Decisions needed:

- exact missing-data thresholds, such as how many weight records are "enough"
- which next questions are too annoying or too personal

### Step 2: Verify Oura Operational Status

Codex does:

- expose Oura connection and sync status in context
- test manual sync for a recent date when credentials are available
- confirm activity data enters advice and review context

User does:

- confirm Oura credentials or OAuth authorization if needed
- decide whether scheduled sync should run by default

Decisions needed:

- whether activity sync should run hourly or less frequently
- whether morning briefing should be enabled locally

### Step 3: Stabilize Record Parsing

Codex does:

- improve parser for light natural-language patterns
- keep raw message storage for unparsed records
- add support for exercise records if not already structured enough

User does:

- provide a few real examples of how they naturally write records
- avoid over-formatting unless necessary

Decisions needed:

- whether to enforce minimal prefixes like `早餐：`, `运动：`, `体重：`
- whether unparsed records should trigger a clarification question

### Step 4: Make Daily Review Use Context

Codex does:

- route daily review generation through context
- include missing-data notes
- include Oura and baseline constraints where relevant

User does:

- read a few generated daily reviews
- mark whether they are useful, too strict, too vague, or missing context

Decisions needed:

- morning review vs evening review
- whether the review should be short by default

### Step 5: Improve Advice Feedback Loop

Codex does:

- make advice outcomes easier to record
- use recent adherence when generating advice
- distinguish "needed replenishment" from "compensatory eating"

User does:

- occasionally report whether advice was followed
- give examples of advice that felt unrealistic

Decisions needed:

- how much friction is acceptable for outcome feedback
- whether the system should ask follow-up questions after advice

## User Decision Checklist

Already decided:

- primary input is ChatGPT or WeChat manual forwarding
- browser page is a debug panel
- natural language plus light keywords is acceptable
- Oura is already part of the system and should be operationalized, not re-designed
- MVP scope is immediate feedback plus daily review
- priority order starts with weight maintenance or slow reduction

Still needs decisions:

- exact time for daily review
- whether scheduled jobs should run automatically
- what counts as enough morning weight data
- what kinds of follow-up questions are acceptable
- what "can eat" should mean after exercise versus late-night craving

## Non-Goals For This MVP

Do not spend the next phase on:

- polishing the browser UI
- exact calorie accounting
- image recognition inside this repo
- a full WeChat automation bridge
- clinical diagnosis
- replacing medical advice

These can come later if the backend loop proves useful.

## Acceptance Criteria

The MVP is ready for real use when:

- the user can send natural-language records through ChatGPT or WeChat and have them stored locally
- `GET /health/context` accurately summarizes known state, missing data, strategy, and next question
- Oura status is visible and recent data can be synced or clearly reported as missing
- meal and weight events produce immediate feedback
- daily review explains the main issue and next adjustment using context
- advice can distinguish craving, late-night compensation, exercise replenishment, and recovery constraints
- the user knows what they need to do each day and what the system is doing automatically
