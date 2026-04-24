from __future__ import annotations

from contextlib import asynccontextmanager
from datetime import date

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import HTMLResponse

from local_health_assistant.config import Settings
from local_health_assistant.models import (
    AdviceOutcomeRequest,
    AdviceRequest,
    GoalUpdateRequest,
    InsightsGenerateRequest,
    MessageIngestRequest,
    OuraSyncRequest,
    ReviewGenerateRequest,
    StatusResponse,
)
from local_health_assistant.oura import OuraClient, OuraOAuthClient
from local_health_assistant.scheduler import MorningBriefingScheduler
from local_health_assistant.service import HealthService
from local_health_assistant.storage import Storage


settings = Settings.load()
storage = Storage(settings.app_paths)
oura_client = OuraClient(settings.oura_access_token, settings.oura_api_base_url)
oura_oauth_client = OuraOAuthClient(
    client_id=settings.oura_client_id,
    client_secret=settings.oura_client_secret,
    redirect_uri=settings.oura_redirect_uri,
    authorize_url=settings.oura_authorize_url,
    token_url=settings.oura_token_url,
)
service = HealthService(storage, oura_client, oura_oauth_client)
morning_scheduler = MorningBriefingScheduler(
    service=service,
    hour=settings.morning_briefing_hour,
    minute=settings.morning_briefing_minute,
    poll_seconds=settings.morning_briefing_poll_seconds,
    activity_sync_enabled=settings.activity_sync_enabled,
    activity_sync_interval_minutes=settings.activity_sync_interval_minutes,
)


@asynccontextmanager
async def lifespan(_: FastAPI):
    should_start_scheduler = settings.morning_briefing_enabled or settings.activity_sync_enabled
    if should_start_scheduler:
        morning_scheduler.start()
    try:
        yield
    finally:
        if should_start_scheduler:
            morning_scheduler.stop()


app = FastAPI(title="Local Health Assistant", version="0.1.0", lifespan=lifespan)


INDEX_HTML = """\
<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>Local Health Assistant</title>
  <style>
    :root {
      color-scheme: light;
      --bg: #f7f5ef;
      --panel: #ffffff;
      --ink: #1e2421;
      --muted: #66716b;
      --line: #d9ded7;
      --accent: #2e7d64;
      --accent-dark: #1f604b;
      --warn: #a45c2a;
      --soft: #eef5f1;
      font-family: Inter, ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
    }

    * {
      box-sizing: border-box;
    }

    body {
      margin: 0;
      background: var(--bg);
      color: var(--ink);
    }

    main {
      width: min(1120px, calc(100vw - 32px));
      margin: 0 auto;
      padding: 28px 0 40px;
    }

    header {
      display: flex;
      justify-content: space-between;
      gap: 16px;
      align-items: flex-end;
      margin-bottom: 20px;
    }

    h1 {
      margin: 0;
      font-size: clamp(28px, 4vw, 44px);
      line-height: 1.05;
      letter-spacing: 0;
    }

    .subtitle {
      margin: 8px 0 0;
      color: var(--muted);
      font-size: 15px;
    }

    .top-actions {
      display: flex;
      gap: 8px;
      flex-wrap: wrap;
      justify-content: flex-end;
    }

    a.button,
    button {
      appearance: none;
      border: 1px solid var(--line);
      background: var(--panel);
      color: var(--ink);
      min-height: 40px;
      padding: 0 14px;
      border-radius: 8px;
      font: inherit;
      font-weight: 650;
      text-decoration: none;
      display: inline-flex;
      align-items: center;
      justify-content: center;
      cursor: pointer;
    }

    button.primary {
      background: var(--accent);
      color: #fff;
      border-color: var(--accent);
    }

    button.primary:hover {
      background: var(--accent-dark);
    }

    button:disabled {
      cursor: wait;
      opacity: 0.65;
    }

    .layout {
      display: grid;
      grid-template-columns: minmax(0, 1.08fr) minmax(320px, 0.92fr);
      gap: 18px;
      align-items: start;
    }

    section {
      background: var(--panel);
      border: 1px solid var(--line);
      border-radius: 8px;
      padding: 18px;
      box-shadow: 0 12px 34px rgba(37, 48, 42, 0.08);
    }

    h2 {
      margin: 0 0 14px;
      font-size: 18px;
      letter-spacing: 0;
    }

    form {
      display: grid;
      gap: 14px;
    }

    .grid {
      display: grid;
      grid-template-columns: repeat(2, minmax(0, 1fr));
      gap: 12px;
    }

    label {
      display: grid;
      gap: 6px;
      color: var(--muted);
      font-size: 13px;
      font-weight: 650;
    }

    input,
    select,
    textarea {
      width: 100%;
      min-height: 42px;
      border: 1px solid var(--line);
      border-radius: 8px;
      background: #fbfcfa;
      color: var(--ink);
      padding: 10px 11px;
      font: inherit;
      font-size: 15px;
      outline: none;
    }

    textarea {
      min-height: 128px;
      resize: vertical;
      line-height: 1.5;
    }

    input:focus,
    select:focus,
    textarea:focus {
      border-color: var(--accent);
      box-shadow: 0 0 0 3px rgba(46, 125, 100, 0.14);
    }

    .form-actions {
      display: flex;
      gap: 10px;
      align-items: center;
      flex-wrap: wrap;
    }

    .status-line {
      color: var(--muted);
      font-size: 13px;
      min-height: 18px;
    }

    .status-line.error {
      color: var(--warn);
    }

    .output {
      margin-top: 14px;
      border: 1px solid var(--line);
      border-radius: 8px;
      background: var(--soft);
      min-height: 180px;
      padding: 14px;
      white-space: pre-wrap;
      overflow-wrap: anywhere;
      font-size: 14px;
      line-height: 1.55;
    }

    .meta {
      display: grid;
      gap: 8px;
      margin-top: 14px;
      color: var(--muted);
      font-size: 13px;
    }

    .pill-row {
      display: flex;
      gap: 8px;
      flex-wrap: wrap;
    }

    .pill {
      border: 1px solid var(--line);
      border-radius: 999px;
      background: #fbfcfa;
      padding: 7px 10px;
      color: var(--muted);
      font-size: 13px;
    }

    @media (max-width: 820px) {
      main {
        width: min(100vw - 20px, 720px);
        padding-top: 18px;
      }

      header,
      .layout,
      .grid {
        grid-template-columns: 1fr;
      }

      header {
        display: grid;
        align-items: start;
      }

      .top-actions {
        justify-content: flex-start;
      }
    }
  </style>
</head>
<body>
  <main>
    <header>
      <div>
        <h1>Local Health Assistant</h1>
        <p class="subtitle">本地目标、日志和即时反馈。</p>
      </div>
      <div class="top-actions">
        <a class="button" href="/docs">API Docs</a>
        <a class="button" href="/health/status">Status</a>
      </div>
    </header>

    <div class="layout">
      <section>
        <h2>基本目标</h2>
        <form id="goals-form">
          <div class="grid">
            <label>
              当前阶段
              <select id="current_phase" name="current_phase">
                <option value="fat_loss">减脂</option>
                <option value="maintenance">维持</option>
                <option value="muscle_gain">增肌</option>
              </select>
            </label>
            <label>
              每周训练目标
              <input id="weekly_training_target" name="weekly_training_target" type="number" min="0" max="14" step="1" />
            </label>
            <label>
              目标体重下限 kg
              <input id="target_weight_min" name="target_weight_min" type="number" min="20" max="250" step="0.1" />
            </label>
            <label>
              目标体重上限 kg
              <input id="target_weight_max" name="target_weight_max" type="number" min="20" max="250" step="0.1" />
            </label>
            <label>
              蛋白下限 g
              <input id="protein_min_g" name="protein_min_g" type="number" min="0" max="400" step="1" />
            </label>
            <label>
              晚间加餐上限
              <input id="late_night_snack_limit" name="late_night_snack_limit" type="number" min="0" max="14" step="1" />
            </label>
            <label>
              热量下限
              <input id="calorie_min" name="calorie_min" type="number" min="0" max="10000" step="10" />
            </label>
            <label>
              热量上限
              <input id="calorie_max" name="calorie_max" type="number" min="0" max="10000" step="10" />
            </label>
          </div>
          <div class="form-actions">
            <button class="primary" type="submit" id="save-goals">保存目标</button>
            <button type="button" id="reload-goals">重新读取</button>
            <span class="status-line" id="goals-status"></span>
          </div>
        </form>
        <div class="meta">
          <div class="pill-row" id="goal-pills"></div>
        </div>
      </section>

      <section>
        <h2>快速记录</h2>
        <form id="log-form">
          <label>
            输入内容
            <textarea id="log-text" name="log-text" placeholder="早餐两个蛋喝了奶茶&#10;早上体重58kg&#10;晚餐吃了牛肉和青菜"></textarea>
          </label>
          <div class="form-actions">
            <button class="primary" type="submit" id="send-log">保存记录</button>
            <span class="status-line" id="log-status"></span>
          </div>
        </form>
        <div class="output" id="log-output">等待输入。</div>
      </section>
    </div>
  </main>

  <script>
    const fields = {
      current_phase: document.querySelector("#current_phase"),
      weekly_training_target: document.querySelector("#weekly_training_target"),
      target_weight_min: document.querySelector("#target_weight_min"),
      target_weight_max: document.querySelector("#target_weight_max"),
      protein_min_g: document.querySelector("#protein_min_g"),
      late_night_snack_limit: document.querySelector("#late_night_snack_limit"),
      calorie_min: document.querySelector("#calorie_min"),
      calorie_max: document.querySelector("#calorie_max")
    };

    const goalsStatus = document.querySelector("#goals-status");
    const logStatus = document.querySelector("#log-status");
    const logOutput = document.querySelector("#log-output");
    const goalPills = document.querySelector("#goal-pills");
    const saveGoalsButton = document.querySelector("#save-goals");
    const sendLogButton = document.querySelector("#send-log");

    function setStatus(node, text, isError = false) {
      node.textContent = text;
      node.classList.toggle("error", isError);
    }

    function numberValue(id) {
      const value = Number(fields[id].value);
      if (!Number.isFinite(value)) {
        throw new Error("请填写完整的数字字段。");
      }
      return value;
    }

    function integerValue(id) {
      return Math.round(numberValue(id));
    }

    function renderGoals(goals) {
      fields.current_phase.value = goals.current_phase || "fat_loss";
      fields.weekly_training_target.value = goals.weekly_training_target ?? "";
      fields.target_weight_min.value = goals.target_weight_range_kg?.min ?? "";
      fields.target_weight_max.value = goals.target_weight_range_kg?.max ?? "";
      fields.protein_min_g.value = goals.protein_min_g ?? "";
      fields.late_night_snack_limit.value = goals.late_night_snack_limit ?? "";
      fields.calorie_min.value = goals.calorie_range?.min ?? "";
      fields.calorie_max.value = goals.calorie_range?.max ?? "";

      goalPills.innerHTML = "";
      [
        `${goals.current_phase}`,
        `${goals.target_weight_range_kg?.min ?? "-"}-${goals.target_weight_range_kg?.max ?? "-"}kg`,
        `蛋白 ${goals.protein_min_g ?? "-"}g`,
        `训练 ${goals.weekly_training_target ?? "-"}次/周`,
        `夜宵 <= ${goals.late_night_snack_limit ?? "-"}`
      ].forEach((text) => {
        const pill = document.createElement("span");
        pill.className = "pill";
        pill.textContent = text;
        goalPills.appendChild(pill);
      });
    }

    async function loadGoals() {
      setStatus(goalsStatus, "读取中...");
      const response = await fetch("/health/goals");
      if (!response.ok) {
        throw new Error(`读取失败：${response.status}`);
      }
      const payload = await response.json();
      renderGoals(payload.goals);
      setStatus(goalsStatus, "已读取");
    }

    function collectGoals() {
      return {
        current_phase: fields.current_phase.value,
        target_weight_range_kg: {
          min: numberValue("target_weight_min"),
          max: numberValue("target_weight_max")
        },
        protein_min_g: integerValue("protein_min_g"),
        calorie_range: {
          min: integerValue("calorie_min"),
          max: integerValue("calorie_max")
        },
        weekly_training_target: integerValue("weekly_training_target"),
        late_night_snack_limit: integerValue("late_night_snack_limit")
      };
    }

    async function saveGoals(event) {
      event.preventDefault();
      try {
        saveGoalsButton.disabled = true;
        setStatus(goalsStatus, "保存中...");
        const goals = collectGoals();
        if (goals.target_weight_range_kg.min > goals.target_weight_range_kg.max) {
          throw new Error("目标体重下限不能大于上限。");
        }
        if (goals.calorie_range.min > goals.calorie_range.max) {
          throw new Error("热量下限不能大于上限。");
        }
        const response = await fetch("/health/goals", {
          method: "PUT",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ goals })
        });
        if (!response.ok) {
          const text = await response.text();
          throw new Error(text || `保存失败：${response.status}`);
        }
        const payload = await response.json();
        renderGoals(payload.goals);
        setStatus(goalsStatus, "已保存");
      } catch (error) {
        setStatus(goalsStatus, error.message || "保存失败", true);
      } finally {
        saveGoalsButton.disabled = false;
      }
    }

    function summarizeFeedback(payload) {
      const records = payload.extracted_records || [];
      const feedback = payload.generated_feedback || [];
      const lines = [
        `event #${payload.conversation_event_id}`,
        records.length ? `records: ${records.map((item) => item.summary).join("; ")}` : "records: none"
      ];
      for (const item of feedback) {
        const data = item.payload || {};
        lines.push("");
        lines.push(`[${item.feedback_type}]`);
        if (data.evaluation_text) lines.push(data.evaluation_text);
        if (data.next_meal_suggestion) lines.push(`下一顿：${data.next_meal_suggestion}`);
        if (data.review_text) lines.push(data.review_text);
        if (data.recommended_action) lines.push(`行动：${data.recommended_action}`);
      }
      return lines.join("\\n");
    }

    async function sendLog(event) {
      event.preventDefault();
      const text = document.querySelector("#log-text").value.trim();
      if (!text) {
        setStatus(logStatus, "请输入内容", true);
        return;
      }
      try {
        sendLogButton.disabled = true;
        setStatus(logStatus, "保存中...");
        const response = await fetch("/health/ingest/message", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            source_channel: "local_ui",
            source_user_id: "local",
            source_chat_id: "browser",
            session_key: "local-ui",
            text
          })
        });
        if (!response.ok) {
          const errorText = await response.text();
          throw new Error(errorText || `保存失败：${response.status}`);
        }
        const payload = await response.json();
        logOutput.textContent = summarizeFeedback(payload);
        setStatus(logStatus, "已保存");
      } catch (error) {
        setStatus(logStatus, error.message || "保存失败", true);
      } finally {
        sendLogButton.disabled = false;
      }
    }

    document.querySelector("#goals-form").addEventListener("submit", saveGoals);
    document.querySelector("#reload-goals").addEventListener("click", () => {
      loadGoals().catch((error) => setStatus(goalsStatus, error.message || "读取失败", true));
    });
    document.querySelector("#log-form").addEventListener("submit", sendLog);
    loadGoals().catch((error) => setStatus(goalsStatus, error.message || "读取失败", true));
  </script>
</body>
</html>
"""


@app.get("/", response_class=HTMLResponse)
def index() -> HTMLResponse:
    return HTMLResponse(INDEX_HTML)


@app.get("/health/status", response_model=StatusResponse)
def health_status() -> StatusResponse:
    return StatusResponse(
        app_name=settings.app_name,
        environment=settings.app_env,
        db_path=str(settings.app_paths.db_path),
        goals_path=str(settings.app_paths.goals_path),
        reviews_dir=str(settings.app_paths.reviews_dir),
        snapshots_dir=str(settings.app_paths.snapshots_dir),
        morning_briefing_enabled=settings.morning_briefing_enabled,
        morning_briefing_time=f"{settings.morning_briefing_hour:02d}:{settings.morning_briefing_minute:02d}",
        activity_sync_enabled=settings.activity_sync_enabled,
        activity_sync_interval_minutes=settings.activity_sync_interval_minutes,
    )


@app.get("/health/goals")
def get_goals() -> dict[str, object]:
    return {"goals": storage.load_goals().model_dump(mode="json")}


@app.get("/health/baseline")
def get_baseline() -> dict[str, object]:
    return service.get_baseline().model_dump(mode="json")


@app.get("/auth/oura/login")
def auth_oura_login() -> dict[str, object]:
    try:
        result = service.start_oura_oauth()
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e)) from e
    return result.model_dump(mode="json")


@app.get("/auth/oura/callback")
def auth_oura_callback(
    code: str | None = Query(default=None),
    state: str | None = Query(default=None),
    error: str | None = Query(default=None),
    error_description: str | None = Query(default=None),
) -> dict[str, object]:
    if error:
        raise HTTPException(
            status_code=400,
            detail={
                "error": error,
                "error_description": error_description or "",
            },
        )
    if not code or not state:
        raise HTTPException(
            status_code=400,
            detail="Missing code or state in Oura callback.",
        )
    try:
        result = service.complete_oura_oauth(code, state)
    except Exception as e:
        raise HTTPException(status_code=502, detail=str(e)) from e
    return result.model_dump(mode="json")


@app.put("/health/goals")
def put_goals(request: GoalUpdateRequest) -> dict[str, object]:
    saved = storage.save_goals(request.goals)
    return {"goals": saved.model_dump(mode="json")}


@app.post("/health/ingest/message")
def ingest_message(request: MessageIngestRequest) -> dict[str, object]:
    result = service.ingest_message(request)
    return result.model_dump(mode="json")


@app.post("/health/reviews/generate")
def generate_review(request: ReviewGenerateRequest) -> dict[str, object]:
    result = service.generate_review(request.target_date)
    return result.model_dump(mode="json")


@app.get("/health/reviews/{target_date}")
def get_review(target_date: date) -> dict[str, object]:
    review = service.get_review(target_date)
    if not review:
        raise HTTPException(status_code=404, detail="Review not found")
    return review.model_dump(mode="json")


@app.get("/health/weights/anomaly/{target_date}")
def get_weight_anomaly_review(target_date: date) -> dict[str, object]:
    result = service.get_abnormal_weight_review(target_date)
    if not result:
        raise HTTPException(status_code=404, detail="Weight anomaly review not found")
    return result.model_dump(mode="json")


@app.post("/health/insights/generate")
def generate_insights(request: InsightsGenerateRequest) -> dict[str, object]:
    result = service.generate_insights(request.target_date)
    return result.model_dump(mode="json")


@app.get("/health/insights/{target_date}")
def get_insights(target_date: date) -> dict[str, object]:
    insights = service.get_insights(target_date)
    if not insights:
        raise HTTPException(status_code=404, detail="Insights not found")
    return insights.model_dump(mode="json")


@app.post("/health/advice/respond")
def advice_respond(request: AdviceRequest) -> dict[str, object]:
    result = service.respond_to_advice(request)
    return result.model_dump(mode="json")


@app.post("/health/advice/outcomes")
def advice_outcomes(request: AdviceOutcomeRequest) -> dict[str, object]:
    result = service.record_advice_outcome(request)
    return result.model_dump(mode="json")


@app.post("/health/oura/sync")
def oura_sync(request: OuraSyncRequest) -> dict[str, object]:
    return service.sync_oura(request.target_date, request.trigger_type)


@app.post("/health/oura/activity-sync")
def oura_activity_sync(request: OuraSyncRequest) -> dict[str, object]:
    return service.run_activity_sync(request.target_date, request.trigger_type)


@app.get("/health/oura/daily/{target_date}")
def get_oura_daily(target_date: date) -> dict[str, object]:
    metrics = storage.get_oura_daily_metrics(target_date)
    if not metrics:
        raise HTTPException(status_code=404, detail="Oura metrics not found")
    return {"metrics": metrics}


@app.post("/health/jobs/morning")
def run_morning_briefing(request: ReviewGenerateRequest) -> dict[str, object]:
    return service.run_morning_briefing(request.target_date)
