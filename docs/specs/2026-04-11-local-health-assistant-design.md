# Local Health Assistant Design

Date: 2026-04-11
Status: Draft approved for implementation planning

## 1. Summary

Build a local health assistant that uses conversation as the primary input, Oura as the objective daily data source, SQLite as the structured fact store, Markdown as the readable daily review format, and JSON as the raw Oura snapshot archive.

Version 1 focuses on a tight closed loop:

- capture diet, hunger, and weight facts from chat
- sync yesterday's Oura data automatically each day
- generate a short daily morning review
- answer diet-related questions using recent personal data and goals
- record the gap between advice and actual behavior

The system is not a calorie tracker. Its core value is a recommendation and calibration system that becomes more realistic as it learns what the user can actually execute.

## 2. Goals

Version 1 must solve these problems:

- turn daily behavior into structured data
- automatically review what happened yesterday
- judge behavior against explicit goals
- adapt advice based on historical execution gaps

Version 1 must also preserve clean boundaries so later clients can be added without redesigning the core.

## 3. Non-Goals

Version 1 does not include:

- Apple Health integration
- smart scale auto-sync
- detailed calorie or macro estimation
- weekly or monthly reporting
- multi-user support
- machine learning personalization
- broad natural-language extraction with low-confidence guessing

## 4. Chosen Approach

The selected architecture is a loosely coupled local health service integrated with `codex-tg`.

`codex-tg` remains the chat channel adapter. The new health service owns:

- data ingestion and structuring
- Oura sync and archival
- goal loading and persistence
- daily review generation
- realtime recommendation logic
- advice outcome calibration

This keeps the business system independent from any single channel while still using chat as the default user interface.

## 5. Alternatives Considered

### Approach A: Embedded directly inside `codex-tg`

Pros:

- simplest deployment
- fewer moving parts

Cons:

- chat transport and health logic become tightly coupled
- Oura sync, API surface, and future clients become harder to evolve
- risk of turning `codex-tg` into an overloaded application shell

### Approach B: Separate local health service plus thin `codex-tg` integration

Pros:

- clear ownership boundaries
- chat adapters stay thin
- future desktop, CLI, or other channels can reuse the same core
- easier to test ingestion, sync, and coaching separately

Cons:

- requires one more local process

### Approach C: Event-sourced architecture first

Pros:

- strongest replay and auditing model
- ideal for long-term correction and learning

Cons:

- too heavy for version 1
- adds complexity before the core loop is proven useful

### Recommendation

Use Approach B.

It gives the system a stable center of gravity around the health domain instead of around a specific chat transport.

## 6. System Context

Existing project context:

- `codex-tg` already handles Telegram, Feishu, and WeChat message transport
- shared local state and Codex session utilities live in `codex-tg/codex_common.py`
- the current chat flow is transport-focused and does not yet own domain-specific health logic

Therefore the health system should attach to `codex-tg` at the message-routing level, not by extending Codex session internals.

## 7. High-Level Architecture

The system has four layers.

### 7.1 Ingest

Responsibilities:

- receive chat messages from enabled conversations
- persist raw conversation events
- extract high-confidence diet, hunger, and weight facts
- classify recommendation requests

### 7.2 Sync

Responsibilities:

- pull yesterday's Oura data on a schedule
- support manual backfill by date
- save raw Oura JSON snapshots
- normalize core daily metrics into SQLite

### 7.3 Coach

Responsibilities:

- generate the short daily morning review
- answer diet-related realtime questions
- create advice records
- later connect outcomes back to advice

### 7.4 Config

Responsibilities:

- load goals from local file
- expose APIs for reading and updating goals
- persist goal versions into SQLite for historical evaluation

## 8. Storage Model

Three storage forms are used on purpose.

### 8.1 SQLite

Primary structured fact store.

Recommended path:

- `data/health/health.db`

### 8.2 Markdown

Human-readable daily review archive.

Recommended path:

- `data/health/daily_reviews/YYYY-MM-DD.md`

### 8.3 JSON

Raw Oura snapshot archive for replay and future parser changes.

Recommended path:

- `data/health/oura_snapshots/YYYY-MM-DD.json`

### 8.4 Goal File

Local editable source of truth for active goals.

Recommended path:

- `data/health/goals/current.yaml`

## 9. Data Model

Version 1 keeps the schema intentionally small.

### 9.1 `conversation_events`

Stores raw incoming events from enabled health conversations.

Fields:

- `id`
- `source_channel`
- `source_user_id`
- `source_chat_id`
- `source_message_id`
- `session_key`
- `occurred_at`
- `text`
- `created_at`

### 9.2 `food_logs`

Stores extracted diet events.

Fields:

- `id`
- `conversation_event_id`
- `logged_at`
- `meal_slot`
- `description`
- `confidence`
- `created_at`

### 9.3 `hunger_logs`

Stores hunger, craving, urge, or loss-of-control signals.

Fields:

- `id`
- `conversation_event_id`
- `logged_at`
- `hunger_level`
- `signal_type`
- `description`
- `confidence`
- `created_at`

### 9.4 `weight_logs`

Stores explicit weight entries.

Fields:

- `id`
- `conversation_event_id`
- `logged_at`
- `weight_kg`
- `confidence`
- `created_at`

### 9.5 `oura_daily_metrics`

One row per date after successful normalization.

Fields:

- `date`
- `sleep_score`
- `total_sleep_minutes`
- `sleep_efficiency`
- `readiness_score`
- `resting_heart_rate`
- `hrv_balance`
- `activity_score`
- `active_calories`
- `steps`
- `snapshot_path`
- `synced_at`

### 9.6 `oura_sync_runs`

Tracks sync attempts and supports idempotency.

Fields:

- `id`
- `target_date`
- `trigger_type`
- `status`
- `error_message`
- `started_at`
- `finished_at`

### 9.7 `goals`

Stores goal snapshots for historical comparison.

Fields:

- `id`
- `effective_from`
- `goal_payload_json`
- `source_version`
- `created_at`

### 9.8 `advice_records`

Stores each coaching recommendation request and response.

Fields:

- `id`
- `conversation_event_id`
- `requested_at`
- `question_text`
- `context_payload_json`
- `advice_text`
- `expected_behavior`
- `created_at`

### 9.9 `advice_outcomes`

Stores whether later behavior followed the recommendation.

Fields:

- `id`
- `advice_record_id`
- `evaluation_window_end`
- `outcome_status`
- `outcome_note`
- `created_at`

### 9.10 `daily_reviews`

Stores daily review metadata.

Fields:

- `date`
- `review_text`
- `markdown_path`
- `key_issue`
- `recommended_adjustment`
- `realism_note`
- `created_at`

## 10. Goal Model

Goals must be explicit and computable. A vague label like "lose fat" is not enough.

Version 1 goal payload supports:

- current phase
- target weight range
- minimum protein target
- calorie range
- weekly training target
- behavior targets such as maximum late-night snack frequency

The file is the editable source of truth. The service also snapshots each active version into SQLite so old advice can still be evaluated against the goals that existed at that time.

## 11. Chat Integration Design

Health mode is conversation-scoped.

Rules:

- only designated conversations are health-enabled
- once enabled, messages in that conversation are automatically inspected
- only high-confidence diet, hunger, and weight facts are structured into records
- all health-enabled messages may still be stored as raw `conversation_events`
- non-health conversations follow the existing `codex-tg` behavior

Recommended control commands:

- `/health_on`
- `/health_off`
- `/health_status`

The transport layer should maintain a per-conversation health mode flag using the existing bot state mechanism.

## 12. Ingestion Rules

Version 1 parsing is rules-first and conservative.

High-confidence examples:

- "早餐两个蛋"
- "现在很饿"
- "72.4kg"

Low-confidence or ambiguous text should remain only in `conversation_events` and must not be forced into structured tables.

This is deliberate. Bad structure is worse than missing structure in the first version.

## 13. Oura Sync Design

Sync policy:

- automatic daily sync pulls yesterday only
- manual sync can backfill a specific date
- successful sync for a date is idempotent
- today's incomplete Oura data is never used for the daily review flow

Version 1 normalized Oura metrics:

- sleep score
- total sleep
- sleep efficiency
- readiness score
- resting heart rate
- HRV balance or closest stable readiness metric available from Oura response
- activity score
- active calories
- steps

Each sync:

1. creates a sync run record
2. fetches Oura data for target date
3. stores raw JSON snapshot
4. extracts normalized metrics
5. upserts `oura_daily_metrics`
6. marks sync run success or failure

## 14. Daily Review Design

A daily review is generated every morning based on yesterday plus recent trend context.

Required output sections:

- yesterday's most important issue
- today's single most useful adjustment
- whether the recommendation is realistic and why

Inputs:

- yesterday's Oura daily metrics
- yesterday's and recent diet or hunger signals
- 3 to 7 day weight trend
- active goals
- recent advice execution patterns

Outputs are stored in both:

- `daily_reviews.review_text`
- `data/health/daily_reviews/YYYY-MM-DD.md`

## 15. Realtime Advice Design

When the user asks a question like "今天能不能吃冰淇淋", the response should be based on personal state rather than generic nutrition rules.

Inputs:

- recent 3-day Oura recovery state
- today's logged diet
- recent weight trend
- active goals
- recent similar advice outcome patterns

Output format:

- conclusion
- why
- more realistic alternative if needed

The system should prefer advice the user can actually execute over theoretically optimal but historically unrealistic advice.

## 16. Calibration Design

Calibration is the most valuable learning loop in version 1.

Each advice record includes an explicit expected behavior. Later conversation or structured events can be evaluated against that expectation.

Version 1 outcome states:

- `followed`
- `partially_followed`
- `not_followed`
- `unknown`

Version 1 calibration remains rule-based and explainable. It should surface patterns such as:

- poor sleep increases late-night compensatory eating
- certain suggestion styles have low follow-through
- a target is consistently too aggressive for current execution ability

## 17. API Surface

Version 1 API should stay small.

### 17.1 Ingest

- `POST /health/ingest/message`
  - accepts conversation metadata and raw user text
  - returns extracted structured facts and whether advice should be generated

### 17.2 Goals

- `GET /health/goals`
- `PUT /health/goals`

### 17.3 Oura

- `POST /health/oura/sync`
  - manual sync by target date
- `GET /health/oura/daily/{date}`

### 17.4 Reviews

- `POST /health/reviews/generate`
  - generate review for a date, normally yesterday
- `GET /health/reviews/{date}`

### 17.5 Advice

- `POST /health/advice/respond`
  - returns recommendation text and creates an advice record

### 17.6 Status

- `GET /health/status`
  - lightweight service and scheduler health summary

## 18. Scheduling

Version 1 needs two scheduled jobs:

- daily Oura sync for yesterday
- daily morning review generation

Both jobs must also be runnable manually through API.

The review job must depend on Oura sync success for the target date. If sync fails, the review should either retry later or clearly mark the missing Oura dependency.

## 19. Failure Handling

Version 1 failure behavior should be simple and explicit.

- failed Oura sync creates a failed sync run with error text
- manual backfill can repair a missed day
- review generation does not silently invent Oura context when sync data is absent
- ambiguous ingest input is preserved raw rather than incorrectly structured

## 20. Security and Locality

This system is local-first.

Requirements:

- SQLite, Markdown, and JSON stay on local disk
- Oura credentials are stored locally and not echoed into chat
- transport adapters should pass only needed message metadata into the health service

## 21. Recommended Technology Choices

For consistency with the existing workspace:

- Python service implementation
- FastAPI for the local HTTP API
- SQLite for persistence
- a lightweight scheduler in the service process
- rules-first extraction logic for version 1

No LLM dependency is required for the first extraction pass. If later used, it should sit behind the health service and operate on explicit, bounded tasks.

## 22. Acceptance Criteria

Version 1 is successful if:

- a designated chat conversation can be health-enabled
- diet, hunger, and weight facts from simple messages are stored correctly
- yesterday's Oura data can sync automatically and also be backfilled manually
- a short daily review is generated each morning from personal data
- a realtime diet question produces a recommendation using recent facts and goals
- advice and later execution gap can be stored and reviewed

## 23. Open Implementation Decisions

These are implementation details, not design blockers:

- exact Oura API field mapping after inspecting live payloads
- whether to use `sqlite3` directly or a thin ORM
- exact scheduler library choice
- exact command names in each chat channel, if transport differences require adaptation

## 24. Phased Delivery

Recommended implementation order:

1. core schema and storage layout
2. goal loading and versioning
3. ingest API and rules-based extraction
4. `codex-tg` conversation health-mode integration
5. Oura manual sync, then scheduled sync
6. daily review generation
7. realtime advice and advice outcome tracking

## 25. Final Scope Check

This design is intentionally narrow.

It builds the smallest useful loop that can accumulate durable data and produce personalized health guidance without pretending to solve every health-tracking problem at once.
