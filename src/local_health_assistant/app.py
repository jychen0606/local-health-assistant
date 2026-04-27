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
    OnboardingUpdateRequest,
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

    .check-grid {
      display: grid;
      grid-template-columns: repeat(2, minmax(0, 1fr));
      gap: 8px;
    }

    .check-item {
      display: flex;
      align-items: center;
      gap: 8px;
      min-height: 42px;
      border: 1px solid var(--line);
      border-radius: 8px;
      background: #fbfcfa;
      padding: 0 10px;
      color: var(--ink);
      font-size: 14px;
      font-weight: 650;
    }

    .check-item input {
      width: 16px;
      min-height: 16px;
      height: 16px;
      margin: 0;
      accent-color: var(--accent);
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
      .grid,
      .check-grid {
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
        <h2>基础信息</h2>
        <form id="goals-form">
          <div class="grid">
            <label>
              当前体重 kg
              <input id="current_weight_kg" name="current_weight_kg" type="number" min="20" max="250" step="0.1" />
            </label>
            <label>
              目标体重 kg
              <input id="target_weight_kg" name="target_weight_kg" type="number" min="20" max="250" step="0.1" />
            </label>
            <label>
              身高 cm
              <input id="height_cm" name="height_cm" type="number" min="100" max="250" step="0.1" />
            </label>
            <label>
              每周运动次数
              <input id="weekly_activity_sessions" name="weekly_activity_sessions" type="number" min="0" max="14" step="1" />
            </label>
            <label>
              每次大约分钟
              <input id="average_session_minutes" name="average_session_minutes" type="number" min="0" max="300" step="5" />
            </label>
            <label>
              主要运动
              <span class="check-grid" id="primary_activities">
                <span class="check-item"><input type="checkbox" value="tennis" />网球</span>
                <span class="check-item"><input type="checkbox" value="boxing" />拳击</span>
                <span class="check-item"><input type="checkbox" value="cardio" />有氧</span>
                <span class="check-item"><input type="checkbox" value="strength" />力量</span>
                <span class="check-item"><input type="checkbox" value="walking" />散步</span>
              </span>
            </label>
          </div>
          <label>
            饮食限制或偏好
            <textarea id="dietary_preferences" name="dietary_preferences" placeholder="例如：晚上容易想吃甜食；不太吃牛肉；想减少夜宵。"></textarea>
          </label>
          <div class="form-actions">
            <button class="primary" type="submit" id="save-goals">保存基础信息</button>
            <button type="button" id="reload-goals">重新读取</button>
            <span class="status-line" id="goals-status"></span>
          </div>
        </form>
        <div class="meta">
          <div class="pill-row" id="goal-pills"></div>
        </div>
        <div class="output" id="derived-output">等待推导。</div>
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

      <section>
        <h2>健康基线</h2>
        <div class="form-actions">
          <button class="primary" type="button" id="import-baseline">导入样例报告</button>
          <button type="button" id="reload-baseline">重新读取</button>
          <span class="status-line" id="baseline-status"></span>
        </div>
        <div class="meta">
          <div class="pill-row" id="baseline-pills"></div>
        </div>
        <div class="output" id="baseline-output">等待读取。</div>
      </section>
    </div>
  </main>

  <script>
    const fields = {
      current_weight_kg: document.querySelector("#current_weight_kg"),
      target_weight_kg: document.querySelector("#target_weight_kg"),
      height_cm: document.querySelector("#height_cm"),
      weekly_activity_sessions: document.querySelector("#weekly_activity_sessions"),
      average_session_minutes: document.querySelector("#average_session_minutes"),
      primary_activities: document.querySelector("#primary_activities"),
      dietary_preferences: document.querySelector("#dietary_preferences")
    };

    const goalsStatus = document.querySelector("#goals-status");
    const logStatus = document.querySelector("#log-status");
    const baselineStatus = document.querySelector("#baseline-status");
    const logOutput = document.querySelector("#log-output");
    const derivedOutput = document.querySelector("#derived-output");
    const baselineOutput = document.querySelector("#baseline-output");
    const goalPills = document.querySelector("#goal-pills");
    const baselinePills = document.querySelector("#baseline-pills");
    const saveGoalsButton = document.querySelector("#save-goals");
    const sendLogButton = document.querySelector("#send-log");
    const importBaselineButton = document.querySelector("#import-baseline");

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

    function optionalNumberValue(id) {
      const raw = fields[id].value.trim();
      if (!raw) return null;
      const value = Number(raw);
      if (!Number.isFinite(value)) {
        throw new Error("请填写有效数字。");
      }
      return value;
    }

    function selectedActivities() {
      return Array.from(fields.primary_activities.querySelectorAll("input:checked")).map((item) => item.value);
    }

    function setSelectedActivities(values) {
      const selected = new Set(values || []);
      Array.from(fields.primary_activities.querySelectorAll("input")).forEach((option) => {
        option.checked = selected.has(option.value);
      });
    }

    function renderOnboarding(payload) {
      const profile = payload.profile || {};
      const goals = payload.goals || {};
      fields.current_weight_kg.value = profile.current_weight_kg ?? "";
      fields.target_weight_kg.value = profile.target_weight_kg ?? "";
      fields.height_cm.value = profile.height_cm ?? "";
      fields.weekly_activity_sessions.value = profile.weekly_activity_sessions ?? "";
      fields.average_session_minutes.value = profile.average_session_minutes ?? "";
      fields.dietary_preferences.value = profile.dietary_preferences ?? "";
      setSelectedActivities(profile.primary_activities || []);

      goalPills.innerHTML = "";
      [
        `阶段 ${goals.current_phase ?? "-"}`,
        `目标区间 ${goals.target_weight_range_kg?.min ?? "-"}-${goals.target_weight_range_kg?.max ?? "-"}kg`,
        `蛋白 ${goals.protein_min_g ?? "-"}g`,
        `热量 ${goals.calorie_range?.min ?? "-"}-${goals.calorie_range?.max ?? "-"}`,
        `运动 ${goals.weekly_training_target ?? "-"}次/周`,
        `夜宵 <= ${goals.late_night_snack_limit ?? "-"}`
      ].forEach((text) => {
        const pill = document.createElement("span");
        pill.className = "pill";
        pill.textContent = text;
        goalPills.appendChild(pill);
      });

      const notes = payload.derived_notes || [];
      derivedOutput.textContent = notes.length ? notes.map((note) => `- ${note}`).join("\\n") : "暂无推导说明。";
    }

    async function loadGoals() {
      setStatus(goalsStatus, "读取中...");
      const response = await fetch("/health/onboarding");
      if (!response.ok) {
        throw new Error(`读取失败：${response.status}`);
      }
      const payload = await response.json();
      renderOnboarding(payload);
      setStatus(goalsStatus, "已读取");
    }

    function collectProfile() {
      const averageMinutes = optionalNumberValue("average_session_minutes");
      const height = optionalNumberValue("height_cm");
      return {
        current_weight_kg: numberValue("current_weight_kg"),
        target_weight_kg: numberValue("target_weight_kg"),
        height_cm: height,
        primary_activities: selectedActivities(),
        weekly_activity_sessions: integerValue("weekly_activity_sessions"),
        average_session_minutes: averageMinutes === null ? null : Math.round(averageMinutes),
        dietary_preferences: fields.dietary_preferences.value.trim() || null
      };
    }

    async function saveGoals(event) {
      event.preventDefault();
      try {
        saveGoalsButton.disabled = true;
        setStatus(goalsStatus, "保存中...");
        const profile = collectProfile();
        const response = await fetch("/health/onboarding", {
          method: "PUT",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ profile })
        });
        if (!response.ok) {
          const text = await response.text();
          throw new Error(text || `保存失败：${response.status}`);
        }
        const payload = await response.json();
        renderOnboarding(payload);
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

    function renderBaseline(payload) {
      const profile = payload.profile || {};
      const markers = payload.markers || [];
      const reports = payload.reports || [];
      baselinePills.innerHTML = "";
      [
        profile.height_cm ? `身高 ${profile.height_cm}cm` : "身高 -",
        profile.weight_kg ? `报告体重 ${profile.weight_kg}kg` : "报告体重 -",
        profile.bmi ? `BMI ${profile.bmi}` : "BMI -",
        `异常指标 ${markers.length}`,
        `报告 ${reports.length}`
      ].forEach((text) => {
        const pill = document.createElement("span");
        pill.className = "pill";
        pill.textContent = text;
        baselinePills.appendChild(pill);
      });

      const lines = [];
      if (reports.length) {
        lines.push(`最近报告：${reports[0].report_date} / ${reports[0].source_type}`);
      } else {
        lines.push("还没有导入健康基线。");
      }
      if (markers.length) {
        lines.push("");
        lines.push("已识别的异常指标：");
        markers.slice(0, 8).forEach((marker) => {
          const unit = marker.unit ? ` ${marker.unit}` : "";
          lines.push(`- ${marker.label}: ${marker.value}${unit} (${marker.severity})`);
        });
        if (markers.length > 8) {
          lines.push(`- 还有 ${markers.length - 8} 项未展开`);
        }
      }
      baselineOutput.textContent = lines.join("\\n");
    }

    async function loadBaseline() {
      setStatus(baselineStatus, "读取中...");
      const response = await fetch("/health/baseline");
      if (!response.ok) {
        throw new Error(`读取失败：${response.status}`);
      }
      const payload = await response.json();
      renderBaseline(payload);
      setStatus(baselineStatus, "已读取");
    }

    async function importBaseline() {
      try {
        importBaselineButton.disabled = true;
        setStatus(baselineStatus, "导入中...");
        const response = await fetch("/health/baseline/import-example", { method: "POST" });
        if (!response.ok) {
          const text = await response.text();
          throw new Error(text || `导入失败：${response.status}`);
        }
        const payload = await response.json();
        renderBaseline(payload);
        setStatus(baselineStatus, "已导入");
        await loadGoals();
      } catch (error) {
        setStatus(baselineStatus, error.message || "导入失败", true);
      } finally {
        importBaselineButton.disabled = false;
      }
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
    document.querySelector("#import-baseline").addEventListener("click", importBaseline);
    document.querySelector("#reload-baseline").addEventListener("click", () => {
      loadBaseline().catch((error) => setStatus(baselineStatus, error.message || "读取失败", true));
    });
    document.querySelector("#log-form").addEventListener("submit", sendLog);
    loadGoals().catch((error) => setStatus(goalsStatus, error.message || "读取失败", true));
    loadBaseline().catch((error) => setStatus(baselineStatus, error.message || "读取失败", true));
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


@app.get("/health/onboarding")
def get_onboarding() -> dict[str, object]:
    return service.get_onboarding().model_dump(mode="json")


@app.put("/health/onboarding")
def put_onboarding(request: OnboardingUpdateRequest) -> dict[str, object]:
    return service.save_onboarding(request.profile).model_dump(mode="json")


@app.get("/health/baseline")
def get_baseline() -> dict[str, object]:
    return service.get_baseline().model_dump(mode="json")


@app.get("/health/context")
def get_context() -> dict[str, object]:
    return service.get_context().model_dump(mode="json")


@app.post("/health/baseline/import-example")
def import_example_baseline() -> dict[str, object]:
    result = service.import_baseline_report(
        str(settings.app_paths.repo_root / "docs" / "examples" / "baseline-2026-01-24.json")
    )
    return result.model_dump(mode="json")


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
