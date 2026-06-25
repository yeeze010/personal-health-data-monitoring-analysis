const state = {
  metrics: [],
  trendMetric: "blood_pressure_systolic",
};

const el = (id) => document.getElementById(id);
const localApiBase =
  ["127.0.0.1", "localhost"].includes(window.location.hostname) && window.location.port !== "8206"
    ? "http://127.0.0.1:8206"
    : "";
const API_BASE = import.meta.env.VITE_API_BASE_URL || localApiBase;

async function api(path, options = {}) {
  const response = await fetch(`${API_BASE}${path}`, {
    headers: { "Content-Type": "application/json", ...(options.headers || {}) },
    ...options,
  });
  const data = await response.json();
  if (!response.ok) {
    throw new Error(data.message || "请求失败");
  }
  return data;
}

function escapeHtml(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;");
}

function formatDateTime(value) {
  if (!value) return "-";
  return new Date(value).toLocaleString("zh-CN", { hour12: false });
}

function levelText(level) {
  return { high: "高风险", medium: "中风险", low: "低风险" }[level] || level;
}

function statusText(status) {
  return {
    open: "待处理",
    in_progress: "进行中",
    done: "已完成",
    handled: "已处理",
    active: "有效",
    review: "复核中",
    passed: "已通过",
    pending: "待授权",
    synced: "已同步",
    failed: "失败",
  }[status] || status;
}

function confidenceText(confidence) {
  return { high: "高可信", medium: "中可信", low: "待补充" }[confidence] || confidence;
}

function reportTypeText(type) {
  return type === "weekly" ? "周报" : "月报";
}

function actionText(action) {
  return {
    create_activity: "新增运动记录",
    create_sleep: "新增睡眠记录",
    create_meal: "新增饮食记录",
    create_family_member: "新增家庭成员",
    create_device: "登记设备",
    handle_risk: "处理异常提醒",
    create_report: "生成健康报告",
    create_record: "新增体征记录",
  }[action] || action;
}

function isMetricRisk(metric) {
  const value = Number(metric.value_numeric);
  return value < Number(metric.normal_min) || value > Number(metric.normal_max);
}

function localNowValue() {
  return new Date(Date.now() - new Date().getTimezoneOffset() * 60000).toISOString().slice(0, 16);
}

async function loadBlueprint() {
  const data = await api("/api/v1/product/blueprint");
  el("positioning").textContent = data.positioning;
  el("coreFlow").innerHTML = data.core_flow
    .map((item, index) => `<span><b>${index + 1}</b>${escapeHtml(item)}</span>`)
    .join("");
  el("roleList").innerHTML = data.roles.map((role) => `<span class="tag">${escapeHtml(role)}</span>`).join("");
  el("moduleList").innerHTML = data.modules.map((item) => `<span class="tag">${escapeHtml(item)}</span>`).join("");
  el("permissionTable").innerHTML = data.permission_matrix
    .map(
      (row) =>
        `<tr><td>${escapeHtml(row.role)}</td><td>${escapeHtml(row.profile)}</td><td>${escapeHtml(row.family)}</td><td>${escapeHtml(row.report)}</td><td>${escapeHtml(row.admin)}</td></tr>`
    )
    .join("");
}

async function loadMetrics() {
  state.metrics = await api("/api/v1/metrics");
  const options = state.metrics
    .map((metric) => `<option value="${metric.code}">${escapeHtml(metric.name)}（${escapeHtml(metric.unit)}）</option>`)
    .join("");
  el("metricSelect").innerHTML = options;
  el("trendMetric").innerHTML = options;
  el("trendMetric").value = state.trendMetric;
}

async function loadSummary() {
  const data = await api("/api/v1/summary");
  const profile = data.profile;
  el("profileName").textContent = profile.name;
  el("profileRole").textContent = profile.role;
  el("profileGender").textContent = profile.gender;
  el("profileBirthday").textContent = profile.birthday;
  el("profileHeight").textContent = `${profile.height_cm} cm`;
  el("profileBloodType").textContent = profile.blood_type;
  el("profileUpdated").textContent = formatDateTime(profile.updated_at);
  el("profileHistory").textContent = profile.medical_history || "暂无";

  const kpi = data.kpis;
  el("healthScore").textContent = kpi.health_score;
  el("totalRecords").textContent = kpi.total_records;
  el("openRisks").textContent = kpi.open_risks;
  el("familyCount").textContent = kpi.family_count;
  el("deviceCount").textContent = kpi.device_count;
  el("weeklySteps").textContent = Number(kpi.weekly_steps).toLocaleString("zh-CN");
  el("avgSleep").textContent = kpi.avg_sleep;
  el("mealCalories").textContent = kpi.meal_calories;
  el("reportCount").textContent = kpi.report_count;
  el("urgentCount").textContent = kpi.open_risks;

  el("latestMetrics").innerHTML = data.latest_metrics
    .map((metric) => {
      const risky = isMetricRisk(metric);
      return `
        <article class="metric-card">
          <span>${escapeHtml(metric.category)} / ${escapeHtml(metric.name)}</span>
          <strong>${Number(metric.value_numeric).toFixed(1)} ${escapeHtml(metric.unit)}</strong>
          <span class="status-pill ${risky ? "status-risk" : "status-ok"}">${risky ? "需要关注" : "正常"}</span>
          <p class="range">参考区间：${metric.normal_min} - ${metric.normal_max} ${escapeHtml(metric.unit)}</p>
        </article>
      `;
    })
    .join("");
}

async function loadTrend() {
  const data = await api(`/api/v1/analytics/trends?metric=${encodeURIComponent(state.trendMetric)}`);
  renderChart(data);
}

function renderChart(data) {
  const points = data.points;
  if (!points.length || !data.metric) {
    el("trendChart").innerHTML = `<div class="empty-state">暂无趋势数据</div>`;
    return;
  }
  const width = 920;
  const height = 342;
  const padding = { top: 28, right: 38, bottom: 58, left: 58 };
  const values = points.map((point) => Number(point.value));
  const min = Math.min(...values, Number(data.metric.normal_min));
  const max = Math.max(...values, Number(data.metric.normal_max));
  const span = Math.max(1, max - min);
  const x = (index) => padding.left + (index * (width - padding.left - padding.right)) / Math.max(1, points.length - 1);
  const y = (value) => height - padding.bottom - ((value - min) / span) * (height - padding.top - padding.bottom);
  const line = points.map((point, index) => `${index === 0 ? "M" : "L"}${x(index)},${y(Number(point.value))}`).join(" ");
  const normalMinY = y(Number(data.metric.normal_min));
  const normalMaxY = y(Number(data.metric.normal_max));
  const labels = points
    .map((point, index) => {
      const cx = x(index);
      const cy = y(Number(point.value));
      const day = point.day.slice(5);
      return `
        <circle cx="${cx}" cy="${cy}" r="4.5" fill="#606c38"></circle>
        <text x="${cx}" y="${cy - 10}" text-anchor="middle" font-size="12" fill="#35402d">${point.value}</text>
        <text x="${cx}" y="${height - 22}" text-anchor="middle" font-size="11" fill="#606c38">${day}</text>
      `;
    })
    .join("");

  el("trendChart").innerHTML = `
    <svg viewBox="0 0 ${width} ${height}" role="img" aria-label="${escapeHtml(data.metric.name)}趋势图">
      <rect x="${padding.left}" y="${normalMaxY}" width="${width - padding.left - padding.right}" height="${normalMinY - normalMaxY}" fill="#cbd4bd"></rect>
      <line x1="${padding.left}" y1="${normalMaxY}" x2="${width - padding.right}" y2="${normalMaxY}" stroke="#606c38" stroke-dasharray="4 4"></line>
      <line x1="${padding.left}" y1="${normalMinY}" x2="${width - padding.right}" y2="${normalMinY}" stroke="#606c38" stroke-dasharray="4 4"></line>
      <text x="${padding.left}" y="${normalMaxY - 8}" font-size="12" fill="#606c38">正常上限 ${data.metric.normal_max}${escapeHtml(data.metric.unit)}</text>
      <text x="${padding.left}" y="${normalMinY + 18}" font-size="12" fill="#606c38">正常下限 ${data.metric.normal_min}${escapeHtml(data.metric.unit)}</text>
      <path d="${line}" fill="none" stroke="#606c38" stroke-width="3"></path>
      ${labels}
    </svg>
  `;
}

async function loadRisks() {
  const risks = await api("/api/v1/risks");
  if (!risks.length) {
    el("riskList").innerHTML = `<div class="empty-state">暂无风险事件</div>`;
    el("riskFocus").textContent = "最近没有待处理异常，当前可进入平稳观察阶段。";
    return;
  }
  const openRisks = risks.filter((risk) => risk.status === "open");
  const priority = openRisks[0] || risks[0];
  el("riskFocus").textContent = `${priority.title}，建议优先完成复测与饮食/作息回访。`;
  el("riskList").innerHTML = risks
    .map(
      (risk) => `
        <article class="risk-item ${risk.status}">
          <div>
            <h3>${escapeHtml(risk.title)}</h3>
            <p>${escapeHtml(risk.description)} · ${levelText(risk.level)} · ${formatDateTime(risk.created_at)}</p>
            ${risk.handled_note ? `<p>处理说明：${escapeHtml(risk.handled_note)}</p>` : ""}
          </div>
          ${
            risk.status === "open"
              ? `<button data-risk-id="${risk.id}" class="handle-risk">标记已处理</button>`
              : `<span class="status-pill status-ok">已处理</span>`
          }
        </article>
      `
    )
    .join("");
}

async function loadBaselines() {
  const baselines = await api("/api/v1/analytics/baselines");
  el("baselineList").innerHTML = baselines.length
    ? baselines
        .map(
          (item) => `
            <article class="baseline-card">
              <div>
                <h3>${escapeHtml(item.metric_name || item.metric_code)}</h3>
                <p>${escapeHtml(item.explanation)}</p>
              </div>
              <div class="baseline-range">
                <strong>${Number(item.baseline_min).toFixed(1)} - ${Number(item.baseline_max).toFixed(1)} ${escapeHtml(item.unit || "")}</strong>
                <span>${confidenceText(item.confidence)} · ${item.sample_count} 条样本</span>
              </div>
            </article>
          `
        )
        .join("")
    : `<div class="empty-state">暂无足够数据生成个人基线</div>`;
}

async function loadActionPlans() {
  const plans = await api("/api/v1/action-plans");
  el("actionPlanList").innerHTML = plans.length
    ? plans
        .map(
          (plan) => `
            <article class="action-plan ${plan.status}">
              <div>
                <h3>${escapeHtml(plan.title)}</h3>
                <p>${escapeHtml(plan.steps)}</p>
                <small>截止日期：${escapeHtml(plan.due_at)} · ${statusText(plan.status)}</small>
              </div>
              ${
                plan.status === "done"
                  ? `<span class="status-pill status-ok">已完成</span>`
                  : `<button class="complete-plan" data-plan-id="${plan.id}">完成计划</button>`
              }
            </article>
          `
        )
        .join("")
    : `<div class="empty-state">当前没有待执行行动计划</div>`;
}

async function loadFamilyPrivacy() {
  const [family, privacy] = await Promise.all([
    api("/api/v1/family/members"),
    api("/api/v1/privacy/authorizations"),
  ]);
  el("familyList").innerHTML = family
    .map(
      (item) => `
        <article class="stack-item">
          <div><h3>${escapeHtml(item.member_name)} · ${escapeHtml(item.relation)}</h3><p>${escapeHtml(item.authorization_scope)}</p></div>
          <span class="status-pill ${item.alert_enabled ? "status-ok" : "status-muted"}">${item.alert_enabled ? "接收提醒" : "不提醒"}</span>
        </article>
      `
    )
    .join("");
  el("privacyList").innerHTML = privacy
    .map(
      (item) => `
        <article class="stack-item">
          <div><h3>${escapeHtml(item.grantee_name)}</h3><p>${escapeHtml(item.scope)} · 到期 ${escapeHtml(item.expires_at || "长期")}</p></div>
          <span class="status-pill ${item.can_export ? "status-risk" : "status-ok"}">${item.can_export ? "可导出" : "只读"}</span>
        </article>
      `
    )
    .join("");
}

async function loadReportsFiles() {
  const [reports, files] = await Promise.all([api("/api/v1/reports"), api("/api/v1/files")]);
  el("reportList").innerHTML = reports.length
    ? reports
        .map(
          (report) => `
        <article class="report-item">
          <div>
            <h3>${reportTypeText(report.report_type)}：${report.period_start} 至 ${report.period_end}</h3>
            <p>${escapeHtml(report.summary)}</p>
          </div>
          <span class="status-pill status-ok">${formatDateTime(report.created_at)}</span>
        </article>
      `
        )
        .join("")
    : `<div class="empty-state">暂无报告</div>`;
  el("fileList").innerHTML = files
    .map(
      (file) => `
        <article class="stack-item">
          <div><h3>${escapeHtml(file.file_name)}</h3><p>${escapeHtml(file.biz_type)} · ${escapeHtml(file.mime_type)} · ${file.size_kb} KB</p></div>
          <span class="status-pill ${file.audit_required ? "status-risk" : "status-ok"}">${file.audit_required ? "需审计" : "免审计"}</span>
        </article>
      `
    )
    .join("");
}

async function loadAcceptance() {
  const checks = await api("/api/v1/acceptance/checks");
  el("acceptanceChecks").innerHTML = checks
    .map(
      (check) => `
        <article class="acceptance-card">
          <span class="status-pill ${check.status === "passed" ? "status-ok" : "status-warning"}">${statusText(check.status)}</span>
          <h3>${escapeHtml(check.category)}：${escapeHtml(check.item)}</h3>
          <p>${escapeHtml(check.evidence || "待补充证据")}</p>
          <small>负责人：${escapeHtml(check.owner)}</small>
        </article>
      `
    )
    .join("");
}

async function loadAdminData() {
  const [devices, rules, logs] = await Promise.all([
    api("/api/v1/devices"),
    api("/api/v1/admin/risk-rules"),
    api("/api/v1/admin/audit-logs"),
  ]);

  const deviceSummary = devices.map((d) => `${d.device_name}（${statusText(d.sync_status)}）`).join("、");
  el("deviceSummaryText").textContent = deviceSummary
    ? `设备接入摘要：${deviceSummary}。`
    : "当前尚未接入设备，需要先完成授权与同步。";

  el("ruleCount").textContent = rules.filter((rule) => rule.enabled).length;
  const latestLog = logs[0]
    ? `${actionText(logs[0].action)}，执行时间 ${formatDateTime(logs[0].created_at)}。`
    : "暂无审计日志。";
  el("latestAudit").textContent = latestLog;
}

async function refreshAll() {
  await loadSummary();
  await Promise.all([
    loadTrend(),
    loadRisks(),
    loadBaselines(),
    loadActionPlans(),
    loadFamilyPrivacy(),
    loadReportsFiles(),
    loadAcceptance(),
    loadAdminData(),
  ]);
}

function setMessage(id, text) {
  el(id).textContent = text;
}

function setupEvents() {
  el("measuredAt").value = localNowValue();

  el("trendMetric").addEventListener("change", async (event) => {
    state.trendMetric = event.target.value;
    await loadTrend();
  });

  el("recordForm").addEventListener("submit", async (event) => {
    event.preventDefault();
    setMessage("recordMessage", "正在保存...");
    await api("/api/v1/records", {
      method: "POST",
      body: JSON.stringify({
        metric_code: el("metricSelect").value,
        value_numeric: Number(el("metricValue").value),
        measured_at: el("measuredAt").value ? new Date(el("measuredAt").value).toISOString() : undefined,
        note: el("recordNote").value,
      }),
    });
    el("metricValue").value = "";
    el("recordNote").value = "";
    setMessage("recordMessage", "体征记录已保存，趋势和异常已刷新。");
    await refreshAll();
  });

  el("activityForm").addEventListener("submit", async (event) => {
    event.preventDefault();
    setMessage("activityMessage", "正在保存...");
    await api("/api/v1/lifestyle/activity", {
      method: "POST",
      body: JSON.stringify({
        activity_type: el("activityType").value,
        steps: Number(el("steps").value),
        distance_km: Number(el("distanceKm").value),
        duration_min: Number(el("durationMin").value),
        calories_kcal: Math.round(Number(el("durationMin").value) * 4.5),
      }),
    });
    setMessage("activityMessage", "运动记录已保存。");
    await refreshAll();
  });

  el("sleepForm").addEventListener("submit", async (event) => {
    event.preventDefault();
    setMessage("sleepMessage", "正在保存...");
    await api("/api/v1/lifestyle/sleep", {
      method: "POST",
      body: JSON.stringify({
        duration_hours: Number(el("sleepHours").value),
        deep_sleep_hours: Number(el("deepSleep").value),
        wake_count: Number(el("wakeCount").value),
        quality_score: Number(el("sleepScore").value),
      }),
    });
    setMessage("sleepMessage", "睡眠记录已保存，系统会自动评估低睡眠风险。");
    await refreshAll();
  });

  el("mealForm").addEventListener("submit", async (event) => {
    event.preventDefault();
    setMessage("mealMessage", "正在保存...");
    await api("/api/v1/lifestyle/meals", {
      method: "POST",
      body: JSON.stringify({
        meal_type: el("mealType").value,
        foods: el("foods").value,
        calories_kcal: Number(el("calories").value),
      }),
    });
    setMessage("mealMessage", "饮食记录已保存。");
    await refreshAll();
  });

  el("familyForm").addEventListener("submit", async (event) => {
    event.preventDefault();
    setMessage("familyMessage", "正在保存...");
    await api("/api/v1/family/members", {
      method: "POST",
      body: JSON.stringify({
        member_name: el("familyName").value,
        relation: el("relation").value,
        age: Number(el("familyAge").value),
        authorization_scope: el("authScope").value,
      }),
    });
    setMessage("familyMessage", "家庭成员已新增。");
    await refreshAll();
  });

  el("deviceForm").addEventListener("submit", async (event) => {
    event.preventDefault();
    setMessage("deviceMessage", "正在登记...");
    await api("/api/v1/devices", {
      method: "POST",
      body: JSON.stringify({
        provider: el("provider").value,
        device_name: el("deviceName").value,
        sync_status: el("syncStatus").value,
      }),
    });
    setMessage("deviceMessage", "设备已登记，可进入授权与同步流程。");
    await refreshAll();
  });

  el("riskList").addEventListener("click", async (event) => {
    const button = event.target.closest(".handle-risk");
    if (!button) return;
    button.disabled = true;
    button.textContent = "处理中...";
    await api(`/api/v1/risks/${button.dataset.riskId}/handle`, {
      method: "PATCH",
      body: JSON.stringify({ handled_note: "用户已确认并安排复测，必要时同步家庭成员。" }),
    });
    await refreshAll();
  });

  el("refreshRisks").addEventListener("click", loadRisks);

  el("rebuildBaseline").addEventListener("click", async () => {
    const button = el("rebuildBaseline");
    button.disabled = true;
    button.textContent = "计算中...";
    await api("/api/v1/analytics/baselines/rebuild", { method: "POST" });
    await loadBaselines();
    button.disabled = false;
    button.textContent = "重建基线";
  });

  el("actionPlanList").addEventListener("click", async (event) => {
    const button = event.target.closest(".complete-plan");
    if (!button) return;
    button.disabled = true;
    button.textContent = "保存中...";
    await api(`/api/v1/action-plans/${button.dataset.planId}/complete`, { method: "PATCH" });
    await Promise.all([loadActionPlans(), loadAdminData()]);
  });

  el("createWeekly").addEventListener("click", async () => {
    await api("/api/v1/reports", { method: "POST", body: JSON.stringify({ report_type: "weekly" }) });
    await refreshAll();
  });

  el("createMonthly").addEventListener("click", async () => {
    await api("/api/v1/reports", { method: "POST", body: JSON.stringify({ report_type: "monthly" }) });
    await refreshAll();
  });
}

async function init() {
  await Promise.all([loadBlueprint(), loadMetrics()]);
  setupEvents();
  await refreshAll();
}

init().catch((error) => {
  document.body.innerHTML = `<main class="section"><div class="empty-state">系统加载失败：${escapeHtml(error.message)}</div></main>`;
});
