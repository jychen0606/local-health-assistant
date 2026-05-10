# Routine V1 PRD

## Purpose

Routine V1 turns the assistant from ad hoc endpoints into a daily operating loop.

The goal is not to make a polished UI. The goal is to define a reliable backend routine that can support ChatGPT/WeChat forwarding, scheduled reminders, meal feedback, Oura-aware activity context, and end-of-day review.

The user wants a system that can:

- query yesterday's data at the start of the day
- give a practical strategy for today
- request lunch and dinner records at predictable times
- evaluate user-submitted meals against the morning strategy and current Oura context
- use Oura activity/recovery data when available
- allow user-supplied activity labels when Oura has intensity data but no activity type
- close the day at midnight and only advise on next-day breakfast

## Primary Loop

Routine V1 has four scheduled nodes plus user-initiated interrupts.

### 1. Start Of Day

Trigger:

- User says "早安", or
- Beijing time 09:30 scheduled trigger.

Inputs:

- Yesterday's Oura daily data:
  - sleep score
  - readiness score
  - activity score
  - active calories
  - steps
  - workout-source heart rate segments, when available
- Yesterday's manual activity records.
- Yesterday's food logs.
- Yesterday's hunger/craving logs.
- Latest weight.
- Today's morning weight, if user reports it.

Weight rule:

- If user gives a new morning weight, use it.
- If no new weight is available, assume weight is unchanged from the latest known weight.
- The output must explicitly mark whether weight is measured or assumed.

Output:

- Yesterday status summary.
- Today's strategy.
- Recovery/activity boundary.
- Meal structure priority.
- What data is missing today.

Important behavior:

- If Oura indicates around 8000 steps and about 350 kcal active burn, treat it as baseline daily walking, not formal training.
- If Oura indicates high activity and the user has supplied an activity label, treat it as a training day.
- If Oura has high activity but no user label, say "high activity/training-like day, type unknown".
- Do not invent sport names from Oura unless Oura explicitly returns them.

### 2. Lunch Check

Trigger:

- Beijing time 12:30 reminder asks user to report lunch.
- Or user proactively reports lunch before/after the reminder.

Inputs:

- Lunch text and/or photo.
- Morning strategy.
- Current Oura activity data available so far.
- Manual activity records so far.
- Hunger/craving feedback, if any.
- Whether user has already trained today.

Output:

- Lunch score or category.
- Objective structure analysis:
  - protein
  - staple/carbohydrate
  - vegetables
  - fat density
  - sweet drink
  - processed/restaurant food
  - portion uncertainty
- Whether lunch follows or deviates from the morning strategy.
- Next-meal recommendation for dinner.

Rules:

- If only a photo is provided and details are uncertain, say what is visible and what is unknown.
- If user has trained or Oura shows training-like data, assess whether replenishment is appropriate.
- If activity is only baseline walking, do not use it as a reason for extra food.
- Feedback should be strict and objective, not comforting.

### 3. Dinner Check

Trigger:

- Beijing time 18:30 reminder asks user to report dinner.
- Or user proactively reports dinner.

Inputs:

- Dinner text and/or photo.
- Morning strategy.
- Lunch feedback.
- Current Oura activity data.
- Manual activity records.
- Hunger/craving logs.

Output:

- Dinner score or category.
- Objective dinner structure analysis.
- Night-risk assessment:
  - late-night snacking risk
  - sweet drink/dessert risk
  - restaurant/high-salt/high-fat stacking
  - under-eating risk after training
- Recommendation for the rest of the night.

Rules:

- The dinner node should not give a generic full-day plan.
- It should focus on what remains today: evening boundary, hydration, whether any additional food is justified, and what not to stack.

### 4. Midnight Close

Trigger:

- Beijing time 00:00.

Inputs:

- Today's meals.
- Today's hunger/craving logs.
- Today's manual activity records.
- Oura activity available so far.
- Any advice outcome feedback.
- Latest weight context.

Output:

- End-of-day review.
- Do not give a full plan for tomorrow.
- Only give next-day breakfast recommendation:
  - whether to eat breakfast
  - what breakfast structure should be
  - when skipping breakfast is acceptable
  - when skipping breakfast is not acceptable

Rules:

- Midnight output closes the day.
- It should avoid opening new complex decisions unless the next breakfast decision needs them.

## User-Initiated Interrupts

User can report at any time:

- food
- hunger/craving
- weight
- activity type
- advice outcome

The system should evaluate the report using:

- current time
- current daily strategy
- prior meals today
- Oura data available so far
- manual activity records
- recovery state
- baseline constraints

Output should include:

- what was recorded
- current assessment
- whether it changes the next scheduled node
- next concrete action

## Data Objects Needed

### `daily_strategy`

Generated at start of day.

Fields:

- date
- weight_source: `measured` or `assumed`
- weight_kg
- morning_summary
- activity_context
- recovery_context
- meal_strategy
- risk_constraints
- missing_info
- created_at

### `routine_events`

Represents scheduled or user-triggered routine nodes.

Fields:

- id
- date
- node_type:
  - `start_of_day`
  - `lunch_check`
  - `dinner_check`
  - `midnight_close`
  - `user_interrupt`
- trigger_type:
  - `scheduled`
  - `user`
- status
- input_summary
- output_summary
- created_at

### `meal_feedback`

Existing meal feedback should be upgraded to reference `daily_strategy`.

Additional fields:

- date
- meal_slot
- daily_strategy_id
- score/category
- structure_assessment_json
- strategy_alignment
- next_meal_suggestion

### `manual_activity_logs`

Already implemented.

Purpose:

- user supplies the activity name when Oura does not return it
- system combines it with Oura evidence

Example:

```text
0430 tennis
```

Stored as:

```text
2026-04-30 activity_type=tennis
```

## Oura Handling

Oura data is evidence, not complete truth.

Current known behavior:

- Oura `workout` collection can be empty even when the App shows an activity.
- Oura `tag`, `enhanced_tag`, and `session` can also be empty.
- Oura `heartrate` can include `source=workout`, which proves training-like heart-rate data exists.
- Daily activity gives steps, active calories, and activity score.

Correct interpretation:

- If Oura returns workout sport/type, use it.
- Else if user supplies activity type and Oura shows high activity or workout-source HR, combine them.
- Else if Oura shows high activity but no type, call it "training-like high activity, type unknown".
- Else if Oura is around 8000 steps and 350 kcal, call it baseline daily walking.

## Abnormal Cases To Handle

1. User does not report morning weight.
   - Use latest weight as assumption.
   - Mark it as assumed.

2. Oura daily data is missing.
   - Still run routine.
   - Mark Oura unavailable.
   - Ask user for activity/recovery context if needed.

3. Oura activity is high but workout collection is empty.
   - Use daily activity and heartrate source evidence.
   - Do not invent activity type.

4. User says activity type after the day.
   - Store manual activity log for that date.
   - Regenerate review if needed.

5. Meal photo has no text.
   - Evaluate visible structure only.
   - Ask for missing details such as drink, portion, oil-heavy components.

6. User reports the same meal twice.
   - Treat as one meal with additional detail, not two separate meal occasions.
   - Current 4/29 example: two dinner records should display as `2 条（1 个餐次）`.

7. User reports restaurant food.
   - Analyze known facts and unknowns.
   - Do not over-warn purely based on baseline markers.

8. User has training day + low recovery.
   - Do not advise hard restriction.
   - Recommend normal meals with protein, staple, and hydration.
   - Avoid using training as permission for extra unstructured eating.

## Tone Requirements

Use strict, objective analysis.

Avoid:

- "不要惩罚自己"
- vague reassurance
- moralizing language
- invented certainty

Prefer:

- facts
- measurable data
- missing information
- risk stack
- next correction

Example:

```text
昨天有手动运动记录：tennis；Oura 同时显示高活动量（活动消耗 970kcal，步数 15240），所以这是训练日，不按普通走路处理。
```

Example:

```text
今天先按训练日后的恢复处理：正常吃正餐，保留主食和蛋白，避免把高活动日转化为额外进食变量。
```

## Open Decisions

Still needs user/product decision:

- Whether meal scoring should be numeric, category-based, or both.
- Whether photo feedback should be supported in MVP or documented as future bridge behavior.
- Whether reminders are local scheduler only or eventually pushed through WeChat/ChatGPT.
- Whether midnight close should run exactly at 00:00 or after the user usually stops eating.
- How strict the breakfast recommendation should be after late-night eating or low-recovery training days.

## Next Implementation Plan

Recommended order:

1. Add `daily_strategy` table and generation service.
2. Add routine node service methods:
   - `run_start_of_day`
   - `run_lunch_check`
   - `run_dinner_check`
   - `run_midnight_close`
3. Add `routine_events` table.
4. Upgrade meal feedback to accept `daily_strategy` and current Oura snapshot.
5. Add scheduled triggers for 09:30, 12:30, 18:30, 00:00.
6. Add endpoints for manual triggering and debugging each node.
7. Add tests or smoke scripts for:
   - missing weight
   - Oura missing
   - high activity without workout type
   - user-supplied tennis
   - duplicate meal detail
   - midnight breakfast-only advice

