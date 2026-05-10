# Agent Handoff Notes

This file is for future Codex/CLI sessions. Read it first when resuming work.

## Current Product Direction

The product is a local-first health assistant. The browser page is a debug panel, not the main product surface.

The real loop is:

1. User records naturally in ChatGPT/WeChat.
2. Codex or a future bridge forwards records into the local service.
3. The service combines manual logs, Oura context, baseline health markers, and prior advice.
4. The service gives objective meal/activity feedback and routine-based daily guidance.

Primary user goal:

- Maintain or slowly reduce weight.
- Reduce compensatory eating and late-night loss of control.
- Distinguish real replenishment needs from compensation loops.
- Use Oura for intensity/recovery evidence, but do not invent activity names that Oura does not return.

## Latest Implemented State

Important commits:

- `e0b0914 Add Oura extended collection sync`
  - OAuth now requests `daily`, `personal`, `workout`, `tag`, `session`, `heartrate`, `spo2`.
  - Added `POST /health/oura/extended-sync` to save raw Oura `tag`, `enhanced_tag`, `session`, `daily_spo2`, and `heartrate` snapshots.
- `08ba737 Add manual activity context to reviews`
  - Added `manual_activity_logs`.
  - Parser can ingest activity text such as `0430 tennis`.
  - Daily reviews combine user-supplied activity type with Oura high-activity evidence.

Known data point:

- `0430 tennis` has been ingested as:
  - `2026-04-30T12:00:00+08:00`
  - `activity_type=tennis`
- Oura did not return `tennis` via `workout`, `tag`, or `session`.
- Oura did return `heartrate.source=workout` for 2026-04-30, including a major activity segment around `08:01-09:46`, max HR about 171, average HR about 132.
- Therefore the correct wording is: user-supplied activity type `tennis` + Oura intensity evidence.

## Current Running Service

Start the service with `.env.local` loaded:

```bash
set -a && source .env.local && set +a && PYTHONDONTWRITEBYTECODE=1 python3 -m local_health_assistant
```

Local URL:

```text
http://127.0.0.1:8000
```

Useful checks:

```bash
git status --short --branch
curl -s http://127.0.0.1:8000/health/context
curl -s http://127.0.0.1:8000/health/reviews/2026-04-30/markdown
```

## Routine V1 PRD

The next product milestone is Routine V1:

```text
docs/specs/2026-05-07-routine-v1-prd.md
```

Do not jump straight into a large implementation. First refine the PRD with:

- node-by-node inputs and outputs
- abnormal cases
- feedback mechanisms
- data contracts
- scheduler behavior
- what user decisions are still needed

## Tone Rules

Feedback should be strict and objective, not overly comforting.

Avoid wording like:

- "不要惩罚自己"
- "清一点就够"
- generic reassurance without concrete analysis

Prefer:

- known facts
- missing data
- risk or uncertainty
- specific next correction
- whether the current evidence supports training-day, normal-walking-day, or insufficient-data handling

Examples:

```text
昨天晚餐是烧烤，补充记录包含牛肉/五花肉、凉皮、可乐和小罐冰红茶；主要问题是红肉/肥肉、重口外食和含糖饮料叠加，蔬菜信息缺失。
```

```text
昨天有手动运动记录：tennis；Oura 同时显示高活动量，所以这是训练日，不按普通走路处理。
```

