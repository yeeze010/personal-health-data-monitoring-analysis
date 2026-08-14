function storedSession() {
  try {
    return JSON.parse(sessionStorage.getItem("health-session") || "null");
  } catch {
    sessionStorage.removeItem("health-session");
    return null;
  }
}

const state = {
  metrics: [],
  devices: [],
  trendMetric: "blood_pressure_systolic",
  session: storedSession(),
};

const deviceEntries = [
  { provider: "Apple Health", device: "Apple Watch / iPhone", scope: "步数、心率、睡眠、血氧", status: "available" },
  { provider: "Health Connect", device: "Android 健康数据", scope: "运动、体重、睡眠、心率", status: "available" },
  { provider: "Samsung Health", device: "Galaxy Watch", scope: "心率、血氧、运动、睡眠", status: "available" },
  { provider: "手环 / 手表", device: "华为、小米、OPPO 等", scope: "步数、心率、睡眠", status: "available" },
  { provider: "蓝牙血压计", device: "家庭血压计", scope: "收缩压、舒张压、测量时间", status: "available" },
  { provider: "蓝牙血糖仪", device: "家用血糖仪", scope: "空腹/餐后血糖、备注", status: "available" },
];

const el = (id) => document.getElementById(id);
const localApiBase =
  ["127.0.0.1", "localhost"].includes(window.location.hostname) && window.location.port !== "8206"
    ? "http://127.0.0.1:8206"
    : "";
const API_BASE = import.meta.env.VITE_API_BASE_URL || localApiBase;

async function api(path, options = {}) {
  const response = await fetch(`${API_BASE}${path}`, {
    ...options,
    headers: {
      "Content-Type": "application/json",
      ...(state.session?.accessToken ? { Authorization: `Bearer ${state.session.accessToken}` } : {}),
      ...(options.headers || {}),
    },
  });
  const data = await response.json().catch(() => ({ message: "服务返回了无法识别的内容" }));
  if (response.status === 401) clearSession();
  if (!response.ok) throw new Error(data.message || "请求失败");
  return data;
}

function clearSession() {
  sessionStorage.removeItem("health-session");
  state.session = null;
  showApp(false);
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

const statusText = (status) =>
  ({
    open: "待处理",
    in_progress: "进行中",
    done: "已完成",
    handled: "已处理",
    active: "有效",
    review: "复核中",
    passed: "已通过",
    pending: "待授权",
    synced: "已同步",
    failed: "连接失败",
  })[status] || status;

const levelText = (level) => ({ high: "高风险", medium: "中风险", low: "低风险" })[level] || level;
const confidenceText = (value) => ({ high: "高可信", medium: "中可信", low: "样本不足" })[value] || value;
const reportTypeText = (type) => (type === "weekly" ? "周报" : "月报");
const permissionText = (permission) =>
  ({
    "*": "全部管理权限",
    "health:read": "查看健康数据",
    "health:write": "记录健康数据",
    "family:manage": "管理家庭授权",
    "device:manage": "管理设备",
    "report:read": "查看报告",
    "report:create": "生成报告",
    "admin:read": "查看管理审计",
  })[permission] || permission;

function hasPermission(permission) {
  const permissions = state.session?.user?.permissions || [];
  return permissions.includes("*") || permissions.includes(permission);
}

function applyRoleVisibility() {
  const devicesSection = el("devices");
  const recordsSection = el("records");
  const familySection = el("family");
  if (devicesSection) devicesSection.hidden = !hasPermission("device:manage");
  if (recordsSection) recordsSection.hidden = !hasPermission("health:write");
  if (familySection) familySection.hidden = !hasPermission("family:manage");
  [el("createWeekly"), el("createMonthly")].forEach((button) => {
    if (button) button.hidden = !hasPermission("report:create");
  });
  const rebuildBaseline = el("rebuildBaseline");
  if (rebuildBaseline) rebuildBaseline.hidden = !hasPermission("health:write");
}

function localNowValue() {
  return new Date(Date.now() - new Date().getTimezoneOffset() * 60000).toISOString().slice(0, 16);
}

function showApp(isLoggedIn) {
  el("loginView").hidden = isLoggedIn;
  el("appView").hidden = !isLoggedIn;
}

function setMessage(id, text) {
  const node = el(id);
  if (node) node.textContent = text;
}

function isMetricRisk(metric) {
  const value = Number(metric.value_numeric);
  return value < Number(metric.normal_min) || value > Number(metric.normal_max);
}

async function withButton(button, busyText, task, messageTarget = "deviceMessage") {
  const original = button.textContent;
  button.disabled = true;
  button.textContent = busyText;
  try {
    await task();
  } catch (error) {
    if (button.closest("#loginForm")) messageTarget = "loginMessage";
    setMessage(messageTarget, `操作失败：${error.message}`);
    if (messageTarget !== "loginMessage") setMessage("reportMessage", `操作失败：${error.message}`);
  } finally {
    button.disabled = false;
    button.textContent = original;
  }
}

async function loadBlueprint() {
  const data = await api("/api/v1/product/blueprint");
  el("positioning").textContent =
    "个人使用 App：先授权健康平台和设备，再记录体征、饮食、睡眠与运动，最后用趋势、提醒、报告和家庭授权完成日常健康管理。";
  el("coreFlow").innerHTML = ["登录", "连接设备", "授权同步", "记录补充", "查看趋势", "处理提醒"]
    .map((item, index) => `<span><b>${index + 1}</b>${item}</span>`)
    .join("");
  const identityTags = [state.session?.user?.role, ...(state.session?.user?.permissions || [])].filter(Boolean);
  el("roleList").innerHTML = identityTags.map((role) => `<span class="tag">${escapeHtml(permissionText(role))}</span>`).join("");
  applyRoleVisibility();
  el("moduleList").innerHTML = data.modules
    .filter((item) => !["Git/GitHub", "测试部署验收"].includes(item))
    .slice(0, 10)
    .map((item) => `<span class="tag">${escapeHtml(item)}</span>`)
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
  const { profile, kpis } = data;
  el("profileName").textContent = profile.name;
  el("profileRole").textContent = profile.role;
  el("profileGender").textContent = profile.gender;
  el("profileBirthday").textContent = profile.birthday;
  el("profileHeight").textContent = `${profile.height_cm} cm`;
  el("profileBloodType").textContent = profile.blood_type;
  el("profileUpdated").textContent = formatDateTime(profile.updated_at);
  el("profileHistory").textContent = profile.medical_history || "暂无";

  el("healthScore").textContent = kpis.health_score;
  el("totalRecords").textContent = kpis.total_records;
  el("openRisks").textContent = kpis.open_risks;
  el("urgentCount").textContent = kpis.open_risks;
  el("familyCount").textContent = kpis.family_count;
  el("deviceCount").textContent = kpis.device_count;
  el("weeklySteps").textContent = Number(kpis.weekly_steps).toLocaleString("zh-CN");
  el("avgSleep").textContent = kpis.avg_sleep;
  el("mealCalories").textContent = kpis.meal_calories;
  el("reportCount").textContent = kpis.report_count;
}

async function loadRecentRecords() {
  const records = await api("/api/v1/records?limit=12");
  const metricMap = new Map(state.metrics.map((metric) => [metric.code, metric]));
  const visible = records.slice(0, 6);
  el("recordCountLabel").textContent = `${records.length} 条，最近保存的记录在前`;
  el("recordList").innerHTML = visible.length
    ? visible
        .map((record) => {
          const metric = metricMap.get(record.metric_code) || {};
          const risk = isMetricRisk({ value_numeric: record.value_numeric, normal_min: metric.normal_min, normal_max: metric.normal_max });
          return `
            <article class="record-row">
              <div><strong>${escapeHtml(metric.name || record.metric_code)}</strong><span>${escapeHtml(record.source)} · ${formatDateTime(record.measured_at)}</span></div>
              <div class="record-value ${risk ? "record-risk" : ""}">${record.value_numeric} ${escapeHtml(metric.unit || "")}</div>
              <small>${escapeHtml(record.note || "未填写备注")}</small>
            </article>`;
        })
        .join("")
    : `<div class="empty-state">还没有保存记录</div>`;
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
      return `
        <circle cx="${cx}" cy="${cy}" r="4.5" fill="#606c38"></circle>
        <text x="${cx}" y="${cy - 10}" text-anchor="middle" font-size="12" fill="#35402d">${point.value}</text>
        <text x="${cx}" y="${height - 22}" text-anchor="middle" font-size="11" fill="#606c38">${point.day.slice(5)}</text>
      `;
    })
    .join("");

  el("trendChart").innerHTML = `
    <svg viewBox="0 0 ${width} ${height}" role="img" aria-label="${escapeHtml(data.metric.name)}趋势图">
      <rect x="${padding.left}" y="${normalMaxY}" width="${width - padding.left - padding.right}" height="${normalMinY - normalMaxY}" fill="#cbd4bd"></rect>
      <line x1="${padding.left}" y1="${normalMaxY}" x2="${width - padding.right}" y2="${normalMaxY}" stroke="#606c38" stroke-dasharray="4 4"></line>
      <line x1="${padding.left}" y1="${normalMinY}" x2="${width - padding.right}" y2="${normalMinY}" stroke="#606c38" stroke-dasharray="4 4"></line>
      <text x="${padding.left}" y="${normalMaxY - 8}" font-size="12" fill="#606c38">参考上限 ${data.metric.normal_max}${escapeHtml(data.metric.unit)}</text>
      <text x="${padding.left}" y="${normalMinY + 18}" font-size="12" fill="#606c38">参考下限 ${data.metric.normal_min}${escapeHtml(data.metric.unit)}</text>
      <path d="${line}" fill="none" stroke="#606c38" stroke-width="3"></path>
      ${labels}
    </svg>
  `;
}

async function loadRisks() {
  const risks = await api("/api/v1/risks");
  if (!risks.length) {
    el("riskList").innerHTML = `<div class="empty-state">暂无异常提醒</div>`;
    el("riskFocus").textContent = "最近没有待处理提醒，可以保持观察。";
    return;
  }
  const priority = risks.find((risk) => risk.status === "open") || risks[0];
  el("riskFocus").textContent = `${priority.title}，建议复测并记录处理结果。`;
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
        </article>`
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
              <div><h3>${escapeHtml(item.metric_name || item.metric_code)}</h3><p>${escapeHtml(item.explanation)}</p></div>
              <div class="baseline-range">
                <strong>${Number(item.baseline_min).toFixed(1)} - ${Number(item.baseline_max).toFixed(1)} ${escapeHtml(item.unit || "")}</strong>
                <span>${confidenceText(item.confidence)} · ${item.sample_count} 条样本</span>
              </div>
            </article>`
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
            </article>`
        )
        .join("")
    : `<div class="empty-state">当前没有待执行行动计划</div>`;
}

async function loadFamilyPrivacy() {
  const [family, privacy] = await Promise.all([api("/api/v1/family/members"), api("/api/v1/privacy/authorizations")]);
  el("familyList").innerHTML = family
    .map(
      (item) => `
        <article class="stack-item">
          <div><h3>${escapeHtml(item.member_name)} · ${escapeHtml(item.relation)}</h3><p>${escapeHtml(item.authorization_scope)}</p></div>
          <span class="status-pill ${item.alert_enabled ? "status-ok" : "status-muted"}">${item.alert_enabled ? "接收提醒" : "不提醒"}</span>
        </article>`
    )
    .join("");
  el("privacyList").innerHTML = privacy
    .map(
      (item) => `
        <article class="stack-item">
          <div><h3>${escapeHtml(item.grantee_name)}</h3><p>${escapeHtml(item.scope)} · 到期 ${escapeHtml(item.expires_at || "长期")}</p></div>
          <span class="status-pill ${item.can_export ? "status-risk" : "status-ok"}">${item.can_export ? "可导出" : "只读"}</span>
        </article>`
    )
    .join("");
}

async function renderFamilyActions() {
  const [family, privacy] = await Promise.all([api("/api/v1/family/members"), api("/api/v1/privacy/authorizations")]);
  const appendAction = (selector, items, idKey, className, label) => {
    const cards = [...document.querySelectorAll(selector)];
    items.forEach((item, index) => {
      const card = cards[index];
      if (!card) return;
      const status = card.querySelector(".status-pill");
      if (item.status === "revoked") {
        status?.classList.remove("status-ok", "status-risk");
        status?.classList.add("status-muted");
        if (status) status.textContent = "已撤销";
        return;
      }
      const actions = document.createElement("div");
      actions.className = "item-actions";
      actions.innerHTML = `<button type="button" class="secondary-button ${className}" data-id="${escapeHtml(item[idKey])}">${label}</button>`;
      card.append(actions);
    });
  };
  appendAction("#familyList .stack-item", family, "id", "revoke-family", "撤销授权");
  appendAction("#privacyList .stack-item", privacy, "id", "revoke-privacy", "撤销访问");
}

async function renderReportActions() {
  const reports = await api("/api/v1/reports");
  const cards = [...document.querySelectorAll("#reportList .report-item")];
  reports.forEach((report, index) => {
    const card = cards[index];
    if (!card) return;
    const actions = document.createElement("div");
    actions.className = "item-actions";
    actions.innerHTML = `<button type="button" class="secondary-button download-report" data-id="${escapeHtml(report.id)}">下载报告</button>`;
    card.append(actions);
  });
}

async function loadReportsFiles() {
  const [reports, files] = await Promise.all([api("/api/v1/reports"), api("/api/v1/files")]);
  el("reportList").innerHTML = reports.length
    ? reports
        .map(
          (report) => `
            <article class="report-item">
              <div><h3>${reportTypeText(report.report_type)}：${report.period_start} 至 ${report.period_end}</h3><p>${escapeHtml(report.summary)}</p></div>
              <span class="status-pill status-ok">${formatDateTime(report.created_at)}</span>
            </article>`
        )
        .join("")
    : `<div class="empty-state">暂无报告</div>`;
  el("fileList").innerHTML = files
    .map(
      (file) => `
        <article class="stack-item">
          <div><h3>${escapeHtml(file.file_name)}</h3><p>${escapeHtml(file.biz_type)} · ${escapeHtml(file.mime_type)} · ${file.size_kb} KB</p></div>
          <span class="status-pill ${file.audit_required ? "status-risk" : "status-ok"}">${file.audit_required ? "需审计" : "免审计"}</span>
        </article>`
    )
    .join("");
}

async function loadAdminData() {
  const canReadAudit = (state.session?.user?.permissions || []).some((permission) => permission === "*" || permission === "admin:read");
  state.devices = await api("/api/v1/devices");
  const devices = state.devices;
  renderDeviceEntries();
  markDeviceStates();
  const logs = canReadAudit ? await api("/api/v1/admin/audit-logs") : [];
  const summary = devices.map((device) => `${device.provider} / ${device.device_name}：${statusText(device.sync_status)}`).join("；");
  el("deviceSummaryText").textContent = summary || "还没有连接设备，请先完成授权。";
  const latestLog = canReadAudit
    ? logs[0] ? `${logs[0].action} · ${formatDateTime(logs[0].created_at)}` : "暂无操作记录"
    : "个人账户的操作会安全记录，仅系统管理员可查看审计明细。";
  el("latestAudit").textContent = latestLog;
}

function renderDeviceEntries() {
  el("deviceEntryList").innerHTML = deviceEntries
    .map(
      (entry, index) => `
        <article class="device-entry">
          <div>
            <span class="status-pill status-muted">${escapeHtml(entry.provider)}</span>
            <h3>${escapeHtml(entry.device)}</h3>
            <p>${escapeHtml(entry.scope)}</p>
          </div>
          <button type="button" data-device-index="${index}">授权连接</button>
        </article>`
    )
    .join("");
}

function markDeviceStates() {
  const cards = [...document.querySelectorAll("#deviceEntryList .device-entry")];
  cards.forEach((card, index) => {
    const entry = deviceEntries[index];
    const record = state.devices.find((device) => device.provider === entry.provider && device.device_name === entry.device);
    const status = document.createElement("span");
    status.className = `status-pill ${record?.sync_status === "synced" ? "status-ok" : record?.sync_status === "failed" ? "status-risk" : "status-muted"}`;
    status.textContent = record ? `本地${statusText(record.sync_status)}` : "未授权";
    card.querySelector("div")?.prepend(status);
    const button = card.querySelector("button");
    if (button) button.textContent = record?.sync_status === "synced" ? "重新记录同步状态" : record?.sync_status === "failed" ? "重试授权" : "授权连接";
  });
}

async function refreshAll() {
  await loadSummary();
  await Promise.all([loadTrend(), loadRecentRecords(), loadRisks(), loadBaselines(), loadActionPlans(), loadFamilyPrivacy(), loadReportsFiles(), loadAdminData()]);
  await renderFamilyActions();
  await renderReportActions();
}

function setupEvents() {
  el("loginForm").addEventListener("submit", async (event) => {
    event.preventDefault();
    const role = el("loginRole").value;
    const username = el("loginUsername").value.trim();
    const password = el("loginPassword").value;
    if (!role || !username || !password) {
      setMessage("loginMessage", "请选择角色并填写用户名、密码。");
      return;
    }
    const button = event.submitter;
    await withButton(button, "正在登录...", async () => {
      const session = await api("/api/v1/auth/login", {
        method: "POST",
        body: JSON.stringify({ role, username, password }),
      });
      state.session = session;
      sessionStorage.setItem("health-session", JSON.stringify(session));
      setMessage("loginMessage", "");
      showApp(true);
      await startApp();
    });
  });

  el("logoutButton").addEventListener("click", () => {
    clearSession();
  });

  el("measuredAt").value = localNowValue();
  el("trendMetric").addEventListener("change", async (event) => {
    state.trendMetric = event.target.value;
    await loadTrend();
  });

  el("deviceEntryList").addEventListener("click", async (event) => {
    const button = event.target.closest("button[data-device-index]");
    if (!button) return;
    const entry = deviceEntries[Number(button.dataset.deviceIndex)];
    await withButton(button, "授权中...", async () => {
      setMessage("deviceMessage", `正在打开 ${entry.provider} 授权流程...`);
      await api("/api/v1/devices", {
        method: "POST",
        body: JSON.stringify({ provider: entry.provider, device_name: entry.device, sync_status: "synced", last_sync_at: new Date().toISOString() }),
      });
      setMessage("deviceMessage", `${entry.provider} 已连接，后续可同步 ${entry.scope}。`);
      await refreshAll();
    });
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
    setMessage("recordMessage", "体征记录已保存，趋势和提醒已刷新。");
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
    setMessage("sleepMessage", "睡眠记录已保存。");
    await refreshAll();
  });

  el("mealForm").addEventListener("submit", async (event) => {
    event.preventDefault();
    setMessage("mealMessage", "正在保存...");
    await api("/api/v1/lifestyle/meals", {
      method: "POST",
      body: JSON.stringify({ meal_type: el("mealType").value, foods: el("foods").value, calories_kcal: Number(el("calories").value) }),
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
    setMessage("familyMessage", "家庭协助人已保存。");
    await refreshAll();
  });

  el("familyList").addEventListener("click", async (event) => {
    const button = event.target.closest(".revoke-family");
    if (!button) return;
    await withButton(button, "撤销中...", async () => {
      await api(`/api/v1/family/members/${button.dataset.id}/revoke`, { method: "PATCH" });
      setMessage("familyMessage", "家庭授权已撤销，提醒已停止。");
      await refreshAll();
    }, "familyMessage");
  });

  el("privacyList").addEventListener("click", async (event) => {
    const button = event.target.closest(".revoke-privacy");
    if (!button) return;
    await withButton(button, "撤销中...", async () => {
      await api(`/api/v1/privacy/authorizations/${button.dataset.id}/revoke`, { method: "PATCH" });
      setMessage("familyMessage", "隐私访问已撤销。");
      await refreshAll();
    }, "familyMessage");
  });

  el("reportList").addEventListener("click", async (event) => {
    const button = event.target.closest(".download-report");
    if (!button) return;
    await withButton(button, "下载中...", async () => {
      const response = await fetch(`${API_BASE}/api/v1/reports/${button.dataset.id}/download`, {
        headers: { Authorization: `Bearer ${state.session.accessToken}` },
      });
      if (!response.ok) {
        const data = await response.json().catch(() => ({}));
        throw new Error(data.message || "报告下载失败");
      }
      const blob = await response.blob();
      const url = URL.createObjectURL(blob);
      const anchor = document.createElement("a");
      anchor.href = url;
      anchor.download = `health-report-${button.dataset.id}.json`;
      anchor.click();
      URL.revokeObjectURL(url);
      setMessage("reportMessage", "报告已下载。");
    }, "reportMessage");
  });

  el("deviceForm").addEventListener("submit", async (event) => {
    event.preventDefault();
    setMessage("deviceMessage", "正在保存设备...");
    await api("/api/v1/devices", {
      method: "POST",
      body: JSON.stringify({ provider: el("provider").value, device_name: el("deviceName").value, sync_status: el("syncStatus").value }),
    });
    setMessage("deviceMessage", "设备连接已保存。");
    await refreshAll();
  });

  el("riskList").addEventListener("click", async (event) => {
    const button = event.target.closest(".handle-risk");
    if (!button) return;
    await withButton(button, "处理中...", async () => {
      await api(`/api/v1/risks/${button.dataset.riskId}/handle`, {
        method: "PATCH",
        body: JSON.stringify({ handled_note: "用户已确认并安排复测，必要时同步家庭协助人。" }),
      });
      await refreshAll();
    });
  });

  el("refreshRisks").addEventListener("click", async () => {
    setMessage("deviceMessage", "提醒已刷新。");
    await loadRisks();
  });

  el("rebuildBaseline").addEventListener("click", async () => {
    await withButton(el("rebuildBaseline"), "计算中...", async () => {
      await api("/api/v1/analytics/baselines/rebuild", { method: "POST" });
      await loadBaselines();
    });
  });

  el("actionPlanList").addEventListener("click", async (event) => {
    const button = event.target.closest(".complete-plan");
    if (!button) return;
    await withButton(button, "保存中...", async () => {
      await api(`/api/v1/action-plans/${button.dataset.planId}/complete`, { method: "PATCH" });
      await Promise.all([loadActionPlans(), loadAdminData()]);
    });
  });

  el("createWeekly").addEventListener("click", async () => {
    setMessage("reportMessage", "正在生成周报...");
    await api("/api/v1/reports", { method: "POST", body: JSON.stringify({ report_type: "weekly" }) });
    setMessage("reportMessage", "周报已生成。");
    await refreshAll();
  });

  el("createMonthly").addEventListener("click", async () => {
    setMessage("reportMessage", "正在生成月报...");
    await api("/api/v1/reports", { method: "POST", body: JSON.stringify({ report_type: "monthly" }) });
    setMessage("reportMessage", "月报已生成。");
    await refreshAll();
  });
}

async function startApp() {
  renderDeviceEntries();
  await Promise.all([loadBlueprint(), loadMetrics()]);
  await refreshAll();
}

async function init() {
  setupEvents();
  showApp(false);
  if (state.session?.accessToken) {
    try {
      state.session.user = await api("/api/v1/auth/me");
      sessionStorage.setItem("health-session", JSON.stringify(state.session));
      showApp(true);
      await startApp();
    } catch (error) {
      clearSession();
      setMessage("loginMessage", error.message);
    }
  }
}

init().catch((error) => {
  clearSession();
  setMessage("loginMessage", `系统加载失败：${error.message}`);
});
