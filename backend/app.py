from __future__ import annotations

import json
import mimetypes
import os
import sqlite3
import uuid
from contextlib import contextmanager
from datetime import datetime, timedelta
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse


ROOT = Path(__file__).resolve().parents[1]
FRONTEND_DIR = ROOT / "frontend"
DB_PATH = ROOT / "data" / "health.db"
DEMO_USER_ID = "u-demo"


METRICS = [
    ("blood_pressure_systolic", "收缩压", "mmHg", 90, 140, "体征"),
    ("blood_pressure_diastolic", "舒张压", "mmHg", 60, 90, "体征"),
    ("blood_glucose", "血糖", "mmol/L", 3.9, 7.8, "体征"),
    ("heart_rate", "心率", "bpm", 55, 100, "体征"),
    ("weight", "体重", "kg", 45, 90, "体征"),
    ("sleep_hours", "睡眠时长", "h", 6, 9, "睡眠"),
    ("blood_oxygen", "血氧", "%", 95, 100, "体征"),
]

PRODUCT_BLUEPRINT = {
    "positioning": "面向个人与家庭的健康生活网络数据监测与分析系统，围绕个人档案、家庭成员、运动、睡眠、饮食、体征、设备接入、健康趋势、异常提醒、隐私授权和健康报告形成数据闭环。",
    "roles": ["个人用户", "家庭管理员", "被照护成员", "健康顾问", "平台运营", "系统管理员"],
    "core_flow": [
        "建立个人档案",
        "录入或同步生活健康数据",
        "趋势分析与异常识别",
        "提醒处理与家庭协同",
        "生成健康报告",
        "隐私审计与验收归档",
    ],
    "modules": [
        "个人档案",
        "家庭成员",
        "运动数据",
        "睡眠数据",
        "饮食数据",
        "体征数据",
        "设备接入",
        "健康趋势",
        "异常提醒",
        "隐私授权",
        "健康报告",
        "文件附件",
        "Git/GitHub",
        "测试部署验收",
    ],
    "pages": [
        "产品定位",
        "健康驾驶舱",
        "生活数据录入",
        "趋势与异常",
        "家庭与隐私",
        "报告与附件",
        "验收中心",
        "工程规范",
    ],
    "permission_matrix": [
        {"role": "个人用户", "profile": "编辑本人", "family": "管理授权家庭", "report": "生成/导出本人报告", "admin": "无"},
        {"role": "家庭管理员", "profile": "查看授权成员", "family": "新增/停用成员", "report": "查看授权报告", "admin": "无"},
        {"role": "健康顾问", "profile": "按授权查看", "family": "不可管理", "report": "查看授权报告", "admin": "不可改规则"},
        {"role": "系统管理员", "profile": "审计查看", "family": "审计查看", "report": "审计归档", "admin": "规则/权限/验收"},
    ],
}


def now_iso() -> str:
    return datetime.now().replace(microsecond=0).isoformat()


def dict_rows(cursor: sqlite3.Cursor) -> list[dict]:
    return [dict(row) for row in cursor.fetchall()]


def get_db() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


@contextmanager
def db_session():
    conn = get_db()
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def ensure_column(db: sqlite3.Connection, table: str, column: str, definition: str) -> None:
    columns = [row["name"] for row in db.execute(f"PRAGMA table_info({table})").fetchall()]
    if column not in columns:
        db.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")


def init_db() -> None:
    with db_session() as db:
        db.executescript(
            """
            CREATE TABLE IF NOT EXISTS users (
              id TEXT PRIMARY KEY,
              name TEXT NOT NULL,
              email TEXT NOT NULL,
              role TEXT NOT NULL,
              status TEXT NOT NULL,
              created_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS health_profiles (
              user_id TEXT PRIMARY KEY,
              gender TEXT,
              birthday TEXT,
              height_cm REAL,
              blood_type TEXT,
              medical_history TEXT,
              updated_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS metric_definitions (
              code TEXT PRIMARY KEY,
              name TEXT NOT NULL,
              unit TEXT NOT NULL,
              normal_min REAL,
              normal_max REAL,
              category TEXT DEFAULT '体征'
            );
            CREATE TABLE IF NOT EXISTS health_records (
              id TEXT PRIMARY KEY,
              user_id TEXT NOT NULL,
              metric_code TEXT NOT NULL,
              value_numeric REAL NOT NULL,
              note TEXT,
              source TEXT NOT NULL,
              measured_at TEXT NOT NULL,
              created_at TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_records_user_metric_time
              ON health_records(user_id, metric_code, measured_at);
            CREATE TABLE IF NOT EXISTS family_members (
              id TEXT PRIMARY KEY,
              owner_user_id TEXT NOT NULL,
              member_name TEXT NOT NULL,
              relation TEXT NOT NULL,
              age INTEGER,
              authorization_scope TEXT NOT NULL,
              alert_enabled INTEGER NOT NULL DEFAULT 1,
              status TEXT NOT NULL,
              created_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS privacy_authorizations (
              id TEXT PRIMARY KEY,
              grantor_user_id TEXT NOT NULL,
              grantee_name TEXT NOT NULL,
              scope TEXT NOT NULL,
              can_export INTEGER NOT NULL DEFAULT 0,
              status TEXT NOT NULL,
              expires_at TEXT,
              created_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS activity_records (
              id TEXT PRIMARY KEY,
              user_id TEXT NOT NULL,
              activity_type TEXT NOT NULL,
              steps INTEGER,
              distance_km REAL,
              duration_min REAL,
              calories_kcal REAL,
              recorded_at TEXT NOT NULL,
              created_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS sleep_records (
              id TEXT PRIMARY KEY,
              user_id TEXT NOT NULL,
              duration_hours REAL NOT NULL,
              deep_sleep_hours REAL,
              wake_count INTEGER,
              quality_score INTEGER,
              recorded_at TEXT NOT NULL,
              created_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS meal_records (
              id TEXT PRIMARY KEY,
              user_id TEXT NOT NULL,
              meal_type TEXT NOT NULL,
              foods TEXT NOT NULL,
              calories_kcal REAL,
              protein_g REAL,
              carbs_g REAL,
              fat_g REAL,
              recorded_at TEXT NOT NULL,
              created_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS device_sources (
              id TEXT PRIMARY KEY,
              user_id TEXT NOT NULL,
              provider TEXT NOT NULL,
              device_name TEXT NOT NULL,
              sync_status TEXT NOT NULL,
              last_sync_at TEXT,
              enabled INTEGER NOT NULL DEFAULT 1,
              created_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS risk_rules (
              id TEXT PRIMARY KEY,
              metric_code TEXT NOT NULL,
              operator TEXT NOT NULL,
              threshold_value REAL NOT NULL,
              risk_level TEXT NOT NULL,
              enabled INTEGER NOT NULL DEFAULT 1,
              description TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS risk_events (
              id TEXT PRIMARY KEY,
              user_id TEXT NOT NULL,
              rule_id TEXT NOT NULL,
              record_id TEXT NOT NULL,
              level TEXT NOT NULL,
              title TEXT NOT NULL,
              status TEXT NOT NULL,
              handled_note TEXT,
              handled_at TEXT,
              created_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS risk_event_timeline (
              id TEXT PRIMARY KEY,
              event_id TEXT NOT NULL,
              actor TEXT NOT NULL,
              action TEXT NOT NULL,
              note TEXT NOT NULL,
              created_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS health_action_plans (
              id TEXT PRIMARY KEY,
              user_id TEXT NOT NULL,
              risk_event_id TEXT,
              title TEXT NOT NULL,
              steps TEXT NOT NULL,
              status TEXT NOT NULL,
              due_at TEXT NOT NULL,
              created_at TEXT NOT NULL,
              completed_at TEXT
            );
            CREATE TABLE IF NOT EXISTS health_baselines (
              id TEXT PRIMARY KEY,
              user_id TEXT NOT NULL,
              metric_code TEXT NOT NULL,
              baseline_avg REAL NOT NULL,
              baseline_min REAL NOT NULL,
              baseline_max REAL NOT NULL,
              sample_count INTEGER NOT NULL,
              confidence TEXT NOT NULL,
              explanation TEXT NOT NULL,
              generated_at TEXT NOT NULL,
              UNIQUE(user_id, metric_code)
            );
            CREATE TABLE IF NOT EXISTS health_reports (
              id TEXT PRIMARY KEY,
              user_id TEXT NOT NULL,
              report_type TEXT NOT NULL,
              period_start TEXT NOT NULL,
              period_end TEXT NOT NULL,
              summary TEXT NOT NULL,
              created_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS files (
              id TEXT PRIMARY KEY,
              owner_user_id TEXT NOT NULL,
              file_name TEXT NOT NULL,
              biz_type TEXT NOT NULL,
              mime_type TEXT NOT NULL,
              size_kb INTEGER NOT NULL,
              linked_to TEXT,
              audit_required INTEGER NOT NULL DEFAULT 1,
              created_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS acceptance_checks (
              id TEXT PRIMARY KEY,
              category TEXT NOT NULL,
              item TEXT NOT NULL,
              status TEXT NOT NULL,
              evidence TEXT,
              owner TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS audit_logs (
              id TEXT PRIMARY KEY,
              actor TEXT NOT NULL,
              action TEXT NOT NULL,
              resource_type TEXT NOT NULL,
              resource_id TEXT,
              created_at TEXT NOT NULL
            );
            """
        )
        ensure_column(db, "metric_definitions", "category", "TEXT DEFAULT '体征'")
        if not db.execute("SELECT 1 FROM users LIMIT 1").fetchone():
            seed(db)
        ensure_reference_content(db)
        ensure_product_seed(db)
        rebuild_health_baselines(db, DEMO_USER_ID)
        ensure_innovation_backfill(db)


def ensure_reference_content(db: sqlite3.Connection) -> None:
    db.executemany(
        """
        INSERT INTO metric_definitions(code, name, unit, normal_min, normal_max, category)
        VALUES (?, ?, ?, ?, ?, ?)
        ON CONFLICT(code) DO UPDATE SET
          name=excluded.name,
          unit=excluded.unit,
          normal_min=excluded.normal_min,
          normal_max=excluded.normal_max,
          category=excluded.category
        """,
        METRICS,
    )
    db.execute(
        "UPDATE users SET name=?, role=? WHERE id=?",
        ("林晓然", "个人用户", DEMO_USER_ID),
    )
    db.execute(
        "UPDATE health_profiles SET gender=?, medical_history=? WHERE user_id=?",
        ("女", "轻度高血压家族史；关注睡眠质量与餐后血糖。", DEMO_USER_ID),
    )
    rules = [
        ("r-sbp-high", "收缩压高于 140 mmHg，需要复测并观察头痛、胸闷等症状"),
        ("r-dbp-high", "舒张压高于 90 mmHg，建议记录连续三天晨间数据"),
        ("r-glucose-high", "血糖高于 7.8 mmol/L，建议标记餐前餐后并调整饮食"),
        ("r-oxygen-low", "血氧低于 95%，建议立即复测并关注呼吸状态"),
        ("r-sleep-low", "睡眠时长低于 6 小时，建议调整作息并减少睡前刺激"),
    ]
    db.executemany("UPDATE risk_rules SET description=? WHERE id=?", [(text, rule_id) for rule_id, text in rules])


def seed(db: sqlite3.Connection) -> None:
    db.execute(
        "INSERT INTO users VALUES (?, ?, ?, ?, ?, ?)",
        (DEMO_USER_ID, "林晓然", "demo@example.com", "个人用户", "active", now_iso()),
    )
    db.execute(
        "INSERT INTO health_profiles VALUES (?, ?, ?, ?, ?, ?, ?)",
        (DEMO_USER_ID, "女", "1992-05-16", 168, "A", "轻度高血压家族史；关注睡眠质量与餐后血糖。", now_iso()),
    )
    db.executemany(
        "INSERT OR IGNORE INTO metric_definitions(code, name, unit, normal_min, normal_max, category) VALUES (?, ?, ?, ?, ?, ?)",
        METRICS,
    )
    rules = [
        ("r-sbp-high", "blood_pressure_systolic", ">", 140, "high", "收缩压高于 140 mmHg，需要复测并观察头痛、胸闷等症状"),
        ("r-dbp-high", "blood_pressure_diastolic", ">", 90, "medium", "舒张压高于 90 mmHg，建议记录连续三天晨间数据"),
        ("r-glucose-high", "blood_glucose", ">", 7.8, "high", "血糖高于 7.8 mmol/L，建议标记餐前餐后并调整饮食"),
        ("r-oxygen-low", "blood_oxygen", "<", 95, "high", "血氧低于 95%，建议立即复测并关注呼吸状态"),
        ("r-sleep-low", "sleep_hours", "<", 6, "medium", "睡眠时长低于 6 小时，建议调整作息并减少睡前刺激"),
    ]
    db.executemany("INSERT OR IGNORE INTO risk_rules VALUES (?, ?, ?, ?, ?, 1, ?)", rules)

    base = datetime.now() - timedelta(days=8)
    samples = []
    for day in range(8):
        measured = (base + timedelta(days=day)).replace(hour=7, minute=30, second=0, microsecond=0).isoformat()
        samples.extend(
            [
                (str(uuid.uuid4()), DEMO_USER_ID, "blood_pressure_systolic", 125 + day * 2, "晨起静息", "manual", measured, now_iso()),
                (str(uuid.uuid4()), DEMO_USER_ID, "blood_pressure_diastolic", 79 + day, "晨起静息", "manual", measured, now_iso()),
                (str(uuid.uuid4()), DEMO_USER_ID, "blood_glucose", 5.6 + (day % 4) * 0.7, "空腹", "manual", measured, now_iso()),
                (str(uuid.uuid4()), DEMO_USER_ID, "heart_rate", 70 + day % 5, "手环同步", "device", measured, now_iso()),
                (str(uuid.uuid4()), DEMO_USER_ID, "weight", 61.5 - day * 0.08, "晨起称重", "manual", measured, now_iso()),
                (str(uuid.uuid4()), DEMO_USER_ID, "sleep_hours", 6.4 + (day % 3) * 0.35, "睡眠记录", "device", measured, now_iso()),
                (str(uuid.uuid4()), DEMO_USER_ID, "blood_oxygen", 97 - (1 if day == 6 else 0), "夜间平均", "device", measured, now_iso()),
            ]
        )
    db.executemany("INSERT INTO health_records VALUES (?, ?, ?, ?, ?, ?, ?, ?)", samples)
    for row in db.execute("SELECT id FROM health_records").fetchall():
        evaluate_record(db, row["id"])


def ensure_product_seed(db: sqlite3.Connection) -> None:
    if not db.execute("SELECT 1 FROM family_members LIMIT 1").fetchone():
        db.executemany(
            "INSERT INTO family_members VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            [
                ("fam-001", DEMO_USER_ID, "林母", "母亲", 63, "体征、异常提醒、报告摘要", 1, "active", now_iso()),
                ("fam-002", DEMO_USER_ID, "周先生", "配偶", 34, "运动、睡眠、异常提醒", 1, "active", now_iso()),
            ],
        )
    if not db.execute("SELECT 1 FROM privacy_authorizations LIMIT 1").fetchone():
        db.executemany(
            "INSERT INTO privacy_authorizations VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            [
                ("auth-001", DEMO_USER_ID, "林母", "查看异常提醒和周报摘要", 0, "active", "2026-12-31", now_iso()),
                ("auth-002", DEMO_USER_ID, "健康顾问王医生", "查看体征趋势、饮食记录、健康报告", 1, "active", "2026-09-30", now_iso()),
            ],
        )
    if not db.execute("SELECT 1 FROM activity_records LIMIT 1").fetchone():
        rows = []
        base = datetime.now() - timedelta(days=6)
        for i in range(7):
            t = (base + timedelta(days=i)).replace(hour=19, minute=10, second=0, microsecond=0).isoformat()
            rows.append((str(uuid.uuid4()), DEMO_USER_ID, "快走", 6200 + i * 480, 4.2 + i * 0.25, 42 + i * 2, 180 + i * 18, t, now_iso()))
        db.executemany("INSERT INTO activity_records VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)", rows)
    if not db.execute("SELECT 1 FROM sleep_records LIMIT 1").fetchone():
        rows = []
        base = datetime.now() - timedelta(days=6)
        for i in range(7):
            t = (base + timedelta(days=i)).replace(hour=7, minute=20, second=0, microsecond=0).isoformat()
            rows.append((str(uuid.uuid4()), DEMO_USER_ID, 6.2 + (i % 4) * 0.45, 1.4 + (i % 3) * 0.2, 1 + i % 3, 72 + i * 2, t, now_iso()))
        db.executemany("INSERT INTO sleep_records VALUES (?, ?, ?, ?, ?, ?, ?, ?)", rows)
    if not db.execute("SELECT 1 FROM meal_records LIMIT 1").fetchone():
        db.executemany(
            "INSERT INTO meal_records VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            [
                (str(uuid.uuid4()), DEMO_USER_ID, "早餐", "燕麦、鸡蛋、无糖豆浆", 430, 24, 52, 12, now_iso(), now_iso()),
                (str(uuid.uuid4()), DEMO_USER_ID, "午餐", "糙米饭、鸡胸肉、西兰花", 680, 42, 76, 18, now_iso(), now_iso()),
                (str(uuid.uuid4()), DEMO_USER_ID, "晚餐", "清蒸鱼、杂蔬、紫薯", 590, 38, 58, 16, now_iso(), now_iso()),
            ],
        )
    if not db.execute("SELECT 1 FROM device_sources LIMIT 1").fetchone():
        db.executemany(
            "INSERT INTO device_sources VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            [
                ("dev-001", DEMO_USER_ID, "Huawei Health", "Band 8", "synced", now_iso(), 1, now_iso()),
                ("dev-002", DEMO_USER_ID, "Manual CSV", "家庭血压计", "pending", None, 1, now_iso()),
            ],
        )
    if not db.execute("SELECT 1 FROM files LIMIT 1").fetchone():
        db.executemany(
            "INSERT INTO files VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            [
                ("file-001", DEMO_USER_ID, "2026-春季体检报告.pdf", "健康报告", "application/pdf", 1280, "report", 1, now_iso()),
                ("file-002", DEMO_USER_ID, "晚餐照片-低盐菜单.jpg", "饮食附件", "image/jpeg", 420, "meal", 1, now_iso()),
            ],
        )
    if not db.execute("SELECT 1 FROM acceptance_checks LIMIT 1").fetchone():
        db.executemany(
            "INSERT INTO acceptance_checks VALUES (?, ?, ?, ?, ?, ?)",
            [
                ("acc-001", "功能", "个人档案、家庭成员、运动/睡眠/饮食/体征数据均可查看或录入", "passed", "页面表单与 API 冒烟测试", "项目经理"),
                ("acc-002", "交互", "异常提醒可从 open 流转为 handled 并写入处理记录", "passed", "风险闭环接口", "测试工程师"),
                ("acc-003", "报表", "健康周报/月报可生成并归档", "passed", "报告接口与页面按钮", "产品经理"),
                ("acc-004", "工程", "README、Git/GitHub 规范、测试和部署说明已落盘", "passed", "docs 与 README", "架构师"),
                ("acc-005", "安全", "隐私授权、附件审计、操作审计具备原型数据闭环", "review", "后续接入真实鉴权", "安全负责人"),
            ],
        )


def audit(db: sqlite3.Connection, action: str, resource_type: str, resource_id: str | None = None) -> None:
    db.execute(
        "INSERT INTO audit_logs VALUES (?, ?, ?, ?, ?, ?)",
        (str(uuid.uuid4()), "demo-user", action, resource_type, resource_id, now_iso()),
    )


def timeline(db: sqlite3.Connection, event_id: str, action: str, note: str, actor: str = "system") -> None:
    db.execute(
        "INSERT INTO risk_event_timeline VALUES (?, ?, ?, ?, ?, ?)",
        (str(uuid.uuid4()), event_id, actor, action, note, now_iso()),
    )


def action_steps(metric_code: str) -> str:
    if metric_code in {"blood_pressure_systolic", "blood_pressure_diastolic"}:
        return "连续 3 天晨间静息复测；记录盐摄入、睡眠与头晕胸闷情况；必要时联系健康顾问。"
    if metric_code == "blood_glucose":
        return "标记餐前/餐后测量时段；连续复测 3 次；同步饮食记录并减少高糖摄入。"
    if metric_code == "sleep_hours":
        return "固定入睡时间；记录睡前咖啡因和屏幕使用；一周后复盘睡眠趋势。"
    if metric_code == "blood_oxygen":
        return "立即复测并确认设备佩戴；持续偏低时联系医生或家属。"
    return "补充一次复测记录；观察趋势变化；必要时创建随访记录。"


def create_action_plan(db: sqlite3.Connection, user_id: str, event_id: str, title: str, metric_code: str) -> None:
    exists = db.execute("SELECT 1 FROM health_action_plans WHERE risk_event_id = ?", (event_id,)).fetchone()
    if exists:
        return
    due_at = (datetime.now() + timedelta(days=3)).date().isoformat()
    db.execute(
        "INSERT INTO health_action_plans VALUES (?, ?, ?, ?, ?, 'open', ?, ?, NULL)",
        (
            str(uuid.uuid4()),
            user_id,
            event_id,
            f"跟进：{title}",
            action_steps(metric_code),
            due_at,
            now_iso(),
        ),
    )


def ensure_innovation_backfill(db: sqlite3.Connection) -> None:
    rows = db.execute(
        """
        SELECT e.id, e.user_id, e.title, e.status, r.metric_code
        FROM risk_events e
        JOIN health_records r ON r.id = e.record_id
        WHERE e.status = 'open'
        """
    ).fetchall()
    for row in rows:
        has_timeline = db.execute("SELECT 1 FROM risk_event_timeline WHERE event_id = ?", (row["id"],)).fetchone()
        if not has_timeline:
            timeline(db, row["id"], "created", "历史风险事件补充时间线，用于行动计划闭环。")
        create_action_plan(db, row["user_id"], row["id"], row["title"], row["metric_code"])


def rebuild_health_baselines(db: sqlite3.Connection, user_id: str) -> list[dict]:
    rows = dict_rows(
        db.execute(
            """
            SELECT r.metric_code, m.name, m.unit, m.normal_min, m.normal_max,
                   COUNT(*) AS sample_count,
                   ROUND(AVG(r.value_numeric), 2) AS avg_value,
                   ROUND(MIN(r.value_numeric), 2) AS min_value,
                   ROUND(MAX(r.value_numeric), 2) AS max_value
            FROM health_records r
            JOIN metric_definitions m ON m.code = r.metric_code
            WHERE r.user_id = ?
            GROUP BY r.metric_code
            ORDER BY m.category, m.name
            """,
            (user_id,),
        )
    )
    generated = []
    for row in rows:
        count = int(row["sample_count"])
        avg_value = float(row["avg_value"])
        observed_min = float(row["min_value"])
        observed_max = float(row["max_value"])
        normal_min = float(row["normal_min"])
        normal_max = float(row["normal_max"])
        tolerance = max((normal_max - normal_min) * 0.08, abs(avg_value) * 0.05, 0.5)
        baseline_min = round(max(normal_min, min(observed_min, avg_value - tolerance)), 2)
        baseline_max = round(min(normal_max, max(observed_max, avg_value + tolerance)), 2)
        confidence = "high" if count >= 14 else "medium" if count >= 7 else "low"
        explanation = (
            f"基于 {count} 条个人历史记录生成，个人均值 {avg_value:g}{row['unit']}，"
            f"建议观察区间 {baseline_min:g}-{baseline_max:g}{row['unit']}。"
        )
        baseline = {
            "id": f"base-{user_id}-{row['metric_code']}",
            "user_id": user_id,
            "metric_code": row["metric_code"],
            "baseline_avg": avg_value,
            "baseline_min": baseline_min,
            "baseline_max": baseline_max,
            "sample_count": count,
            "confidence": confidence,
            "explanation": explanation,
            "generated_at": now_iso(),
        }
        db.execute(
            """
            INSERT INTO health_baselines
            VALUES (:id, :user_id, :metric_code, :baseline_avg, :baseline_min, :baseline_max,
                    :sample_count, :confidence, :explanation, :generated_at)
            ON CONFLICT(user_id, metric_code) DO UPDATE SET
              baseline_avg=excluded.baseline_avg,
              baseline_min=excluded.baseline_min,
              baseline_max=excluded.baseline_max,
              sample_count=excluded.sample_count,
              confidence=excluded.confidence,
              explanation=excluded.explanation,
              generated_at=excluded.generated_at
            """,
            baseline,
        )
        generated.append(baseline)
    audit(db, "rebuild_health_baselines", "health_baselines", user_id)
    return generated


def evaluate_record(db: sqlite3.Connection, record_id: str) -> None:
    record = db.execute("SELECT * FROM health_records WHERE id = ?", (record_id,)).fetchone()
    if not record:
        return
    rules = db.execute(
        "SELECT * FROM risk_rules WHERE metric_code = ? AND enabled = 1",
        (record["metric_code"],),
    ).fetchall()
    metric = db.execute("SELECT name, unit FROM metric_definitions WHERE code = ?", (record["metric_code"],)).fetchone()
    for rule in rules:
        value = float(record["value_numeric"])
        threshold = float(rule["threshold_value"])
        matched = (rule["operator"] == ">" and value > threshold) or (rule["operator"] == "<" and value < threshold)
        if not matched:
            continue
        exists = db.execute(
            "SELECT 1 FROM risk_events WHERE rule_id = ? AND record_id = ?",
            (rule["id"], record_id),
        ).fetchone()
        if exists:
            continue
        title = f"{metric['name']}异常：{value:g}{metric['unit']}"
        event_id = str(uuid.uuid4())
        db.execute(
            "INSERT INTO risk_events VALUES (?, ?, ?, ?, ?, ?, 'open', NULL, NULL, ?)",
            (event_id, record["user_id"], rule["id"], record_id, rule["risk_level"], title, now_iso()),
        )
        timeline(db, event_id, "created", f"系统根据规则“{rule['description']}”生成异常提醒。")
        create_action_plan(db, record["user_id"], event_id, title, record["metric_code"])


def create_report(db: sqlite3.Connection, user_id: str, report_type: str) -> dict:
    days = 30 if report_type == "monthly" else 7
    end = datetime.now()
    start = end - timedelta(days=days)
    row = db.execute(
        """
        SELECT COUNT(*) AS total_records, ROUND(AVG(value_numeric), 2) AS avg_value
        FROM health_records
        WHERE user_id = ? AND measured_at >= ?
        """,
        (user_id, start.isoformat()),
    ).fetchone()
    open_risks = db.execute("SELECT COUNT(*) AS c FROM risk_events WHERE user_id = ? AND status='open'", (user_id,)).fetchone()["c"]
    activity = db.execute(
        "SELECT COALESCE(SUM(steps), 0) AS steps FROM activity_records WHERE user_id = ? AND recorded_at >= ?",
        (user_id, start.isoformat()),
    ).fetchone()["steps"]
    sleep = db.execute(
        "SELECT ROUND(AVG(duration_hours), 2) AS avg_sleep FROM sleep_records WHERE user_id = ? AND recorded_at >= ?",
        (user_id, start.isoformat()),
    ).fetchone()["avg_sleep"]
    summary = (
        f"{'月报' if report_type == 'monthly' else '周报'}：周期内采集健康数据 {row['total_records']} 条，"
        f"累计步数 {int(activity)} 步，平均睡眠 {sleep or 0} 小时，"
        f"仍有 {open_risks} 条异常提醒待处理。建议结合饮食、睡眠和血压趋势安排复测。"
    )
    report = {
        "id": str(uuid.uuid4()),
        "user_id": user_id,
        "report_type": report_type,
        "period_start": start.date().isoformat(),
        "period_end": end.date().isoformat(),
        "summary": summary,
        "created_at": now_iso(),
    }
    db.execute("INSERT INTO health_reports VALUES (?, ?, ?, ?, ?, ?, ?)", tuple(report.values()))
    audit(db, "create_report", "health_reports", report["id"])
    return report


class AppHandler(BaseHTTPRequestHandler):
    server_version = "PersonalHealthMonitor/2.0"

    def do_OPTIONS(self) -> None:
        self.send_response(HTTPStatus.NO_CONTENT)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, PUT, PATCH, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path.startswith("/api/"):
            self.route_api("GET", parsed.path, parse_qs(parsed.query))
            return
        self.serve_static(parsed.path)

    def do_POST(self) -> None:
        parsed = urlparse(self.path)
        self.route_api("POST", parsed.path, parse_qs(parsed.query))

    def do_PUT(self) -> None:
        parsed = urlparse(self.path)
        self.route_api("PUT", parsed.path, parse_qs(parsed.query))

    def do_PATCH(self) -> None:
        parsed = urlparse(self.path)
        self.route_api("PATCH", parsed.path, parse_qs(parsed.query))

    def route_api(self, method: str, path: str, query: dict[str, list[str]]) -> None:
        try:
            with db_session() as db:
                if method == "GET" and path == "/api/v1/health":
                    self.json({"status": "ok", "time": now_iso()})
                elif method == "GET" and path == "/api/v1/product/blueprint":
                    self.json(PRODUCT_BLUEPRINT)
                elif method == "GET" and path == "/api/v1/metrics":
                    self.json(dict_rows(db.execute("SELECT * FROM metric_definitions ORDER BY category, name")))
                elif method == "GET" and path == "/api/v1/profile":
                    self.json(self.profile(db))
                elif method == "PUT" and path == "/api/v1/profile":
                    self.json(self.update_profile(db))
                elif method == "GET" and path == "/api/v1/summary":
                    self.json(self.summary(db))
                elif method == "GET" and path == "/api/v1/records":
                    self.json(self.records(db, query))
                elif method == "POST" and path == "/api/v1/records":
                    self.json(self.create_record(db), HTTPStatus.CREATED)
                elif method == "GET" and path == "/api/v1/analytics/trends":
                    self.json(self.trends(db, query))
                elif method == "GET" and path == "/api/v1/analytics/baselines":
                    self.json(self.baselines(db))
                elif method == "POST" and path == "/api/v1/analytics/baselines/rebuild":
                    self.json(rebuild_health_baselines(db, DEMO_USER_ID), HTTPStatus.CREATED)
                elif method == "GET" and path == "/api/v1/risks":
                    self.json(self.risks(db))
                elif method == "GET" and path.startswith("/api/v1/risks/") and path.endswith("/timeline"):
                    self.json(self.risk_timeline(db, path))
                elif method == "PATCH" and path.startswith("/api/v1/risks/") and path.endswith("/handle"):
                    self.json(self.handle_risk(db, path))
                elif method == "GET" and path == "/api/v1/action-plans":
                    self.json(self.action_plans(db))
                elif method == "PATCH" and path.startswith("/api/v1/action-plans/") and path.endswith("/complete"):
                    self.json(self.complete_action_plan(db, path))
                elif method == "GET" and path == "/api/v1/reports":
                    self.json(dict_rows(db.execute("SELECT * FROM health_reports ORDER BY created_at DESC")))
                elif method == "POST" and path == "/api/v1/reports":
                    body = self.read_json()
                    self.json(create_report(db, DEMO_USER_ID, body.get("report_type", "weekly")), HTTPStatus.CREATED)
                elif method == "GET" and path == "/api/v1/family/members":
                    self.json(dict_rows(db.execute("SELECT * FROM family_members ORDER BY created_at DESC")))
                elif method == "POST" and path == "/api/v1/family/members":
                    self.json(self.create_family_member(db), HTTPStatus.CREATED)
                elif method == "GET" and path == "/api/v1/privacy/authorizations":
                    self.json(dict_rows(db.execute("SELECT * FROM privacy_authorizations ORDER BY created_at DESC")))
                elif method == "GET" and path == "/api/v1/lifestyle/activity":
                    self.json(dict_rows(db.execute("SELECT * FROM activity_records ORDER BY recorded_at DESC LIMIT 30")))
                elif method == "POST" and path == "/api/v1/lifestyle/activity":
                    self.json(self.create_activity(db), HTTPStatus.CREATED)
                elif method == "GET" and path == "/api/v1/lifestyle/sleep":
                    self.json(dict_rows(db.execute("SELECT * FROM sleep_records ORDER BY recorded_at DESC LIMIT 30")))
                elif method == "POST" and path == "/api/v1/lifestyle/sleep":
                    self.json(self.create_sleep(db), HTTPStatus.CREATED)
                elif method == "GET" and path == "/api/v1/lifestyle/meals":
                    self.json(dict_rows(db.execute("SELECT * FROM meal_records ORDER BY recorded_at DESC LIMIT 30")))
                elif method == "POST" and path == "/api/v1/lifestyle/meals":
                    self.json(self.create_meal(db), HTTPStatus.CREATED)
                elif method == "GET" and path == "/api/v1/devices":
                    self.json(dict_rows(db.execute("SELECT * FROM device_sources ORDER BY created_at DESC")))
                elif method == "POST" and path == "/api/v1/devices":
                    self.json(self.create_device(db), HTTPStatus.CREATED)
                elif method == "GET" and path == "/api/v1/files":
                    self.json(dict_rows(db.execute("SELECT * FROM files ORDER BY created_at DESC")))
                elif method == "GET" and path == "/api/v1/acceptance/checks":
                    self.json(dict_rows(db.execute("SELECT * FROM acceptance_checks ORDER BY id")))
                elif method == "GET" and path == "/api/v1/admin/users":
                    self.json(dict_rows(db.execute("SELECT id, name, email, role, status, created_at FROM users")))
                elif method == "GET" and path == "/api/v1/admin/risk-rules":
                    self.json(dict_rows(db.execute("SELECT * FROM risk_rules ORDER BY metric_code")))
                elif method == "GET" and path == "/api/v1/admin/audit-logs":
                    self.json(dict_rows(db.execute("SELECT * FROM audit_logs ORDER BY created_at DESC LIMIT 50")))
                else:
                    self.json({"message": "接口不存在"}, HTTPStatus.NOT_FOUND)
        except ValueError as exc:
            self.json({"message": str(exc)}, HTTPStatus.BAD_REQUEST)
        except Exception as exc:
            self.json({"message": "服务器处理失败", "detail": str(exc)}, HTTPStatus.INTERNAL_SERVER_ERROR)

    def profile(self, db: sqlite3.Connection) -> dict:
        row = db.execute(
            """
            SELECT u.id, u.name, u.email, u.role, p.gender, p.birthday, p.height_cm,
                   p.blood_type, p.medical_history, p.updated_at
            FROM users u
            JOIN health_profiles p ON p.user_id = u.id
            WHERE u.id = ?
            """,
            (DEMO_USER_ID,),
        ).fetchone()
        return dict(row)

    def update_profile(self, db: sqlite3.Connection) -> dict:
        body = self.read_json()
        allowed = ["gender", "birthday", "height_cm", "blood_type", "medical_history"]
        values = {key: body[key] for key in allowed if key in body}
        if not values:
            raise ValueError("没有可更新的档案字段")
        assignments = ", ".join([f"{key}=?" for key in values])
        db.execute(
            f"UPDATE health_profiles SET {assignments}, updated_at=? WHERE user_id=?",
            (*values.values(), now_iso(), DEMO_USER_ID),
        )
        audit(db, "update_profile", "health_profiles", DEMO_USER_ID)
        return self.profile(db)

    def summary(self, db: sqlite3.Connection) -> dict:
        latest = dict_rows(
            db.execute(
                """
                SELECT m.code, m.name, m.unit, m.category, r.value_numeric, r.measured_at, m.normal_min, m.normal_max
                FROM metric_definitions m
                JOIN health_records r ON r.metric_code = m.code
                WHERE r.user_id = ?
                  AND r.measured_at = (
                    SELECT MAX(r2.measured_at)
                    FROM health_records r2
                    WHERE r2.metric_code = m.code AND r2.user_id = ?
                  )
                ORDER BY m.category, m.name
                """,
                (DEMO_USER_ID, DEMO_USER_ID),
            )
        )
        open_risks = db.execute("SELECT COUNT(*) AS c FROM risk_events WHERE status='open'").fetchone()["c"]
        total_records = db.execute("SELECT COUNT(*) AS c FROM health_records").fetchone()["c"]
        report_count = db.execute("SELECT COUNT(*) AS c FROM health_reports").fetchone()["c"]
        family_count = db.execute("SELECT COUNT(*) AS c FROM family_members WHERE status='active'").fetchone()["c"]
        device_count = db.execute("SELECT COUNT(*) AS c FROM device_sources WHERE enabled=1").fetchone()["c"]
        weekly_steps = db.execute(
            "SELECT COALESCE(SUM(steps), 0) AS c FROM activity_records WHERE recorded_at >= ?",
            ((datetime.now() - timedelta(days=7)).isoformat(),),
        ).fetchone()["c"]
        avg_sleep = db.execute(
            "SELECT ROUND(AVG(duration_hours), 1) AS c FROM sleep_records WHERE recorded_at >= ?",
            ((datetime.now() - timedelta(days=7)).isoformat(),),
        ).fetchone()["c"]
        meal_calories = db.execute(
            "SELECT COALESCE(SUM(calories_kcal), 0) AS c FROM meal_records WHERE date(recorded_at)=date('now')",
        ).fetchone()["c"]
        return {
            "profile": self.profile(db),
            "kpis": {
                "total_records": total_records,
                "open_risks": open_risks,
                "report_count": report_count,
                "health_score": max(60, 96 - open_risks * 6),
                "family_count": family_count,
                "device_count": device_count,
                "weekly_steps": int(weekly_steps or 0),
                "avg_sleep": avg_sleep or 0,
                "meal_calories": int(meal_calories or 0),
            },
            "latest_metrics": latest,
        }

    def records(self, db: sqlite3.Connection, query: dict[str, list[str]]) -> list[dict]:
        metric = query.get("metric", [None])[0]
        params: list[str] = [DEMO_USER_ID]
        where = "r.user_id = ?"
        if metric:
            where += " AND r.metric_code = ?"
            params.append(metric)
        return dict_rows(
            db.execute(
                f"""
                SELECT r.*, m.name AS metric_name, m.unit, m.category
                FROM health_records r
                JOIN metric_definitions m ON m.code = r.metric_code
                WHERE {where}
                ORDER BY r.measured_at DESC
                LIMIT 100
                """,
                params,
            )
        )

    def create_record(self, db: sqlite3.Connection) -> dict:
        body = self.read_json()
        metric_code = body.get("metric_code")
        value = body.get("value_numeric")
        if not metric_code or value is None:
            raise ValueError("metric_code 和 value_numeric 必填")
        metric = db.execute("SELECT * FROM metric_definitions WHERE code = ?", (metric_code,)).fetchone()
        if not metric:
            raise ValueError("指标不存在")
        record = {
            "id": str(uuid.uuid4()),
            "user_id": DEMO_USER_ID,
            "metric_code": metric_code,
            "value_numeric": float(value),
            "note": body.get("note", ""),
            "source": body.get("source", "manual"),
            "measured_at": body.get("measured_at") or now_iso(),
            "created_at": now_iso(),
        }
        db.execute("INSERT INTO health_records VALUES (?, ?, ?, ?, ?, ?, ?, ?)", tuple(record.values()))
        evaluate_record(db, record["id"])
        rebuild_health_baselines(db, DEMO_USER_ID)
        audit(db, "create_record", "health_records", record["id"])
        return record

    def create_family_member(self, db: sqlite3.Connection) -> dict:
        body = self.read_json()
        if not body.get("member_name") or not body.get("relation"):
            raise ValueError("成员姓名和关系必填")
        row = {
            "id": str(uuid.uuid4()),
            "owner_user_id": DEMO_USER_ID,
            "member_name": body["member_name"],
            "relation": body["relation"],
            "age": int(body.get("age") or 0),
            "authorization_scope": body.get("authorization_scope", "异常提醒"),
            "alert_enabled": 1 if body.get("alert_enabled", True) else 0,
            "status": body.get("status", "active"),
            "created_at": now_iso(),
        }
        db.execute("INSERT INTO family_members VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)", tuple(row.values()))
        audit(db, "create_family_member", "family_members", row["id"])
        return row

    def create_activity(self, db: sqlite3.Connection) -> dict:
        body = self.read_json()
        row = {
            "id": str(uuid.uuid4()),
            "user_id": DEMO_USER_ID,
            "activity_type": body.get("activity_type", "快走"),
            "steps": int(body.get("steps") or 0),
            "distance_km": float(body.get("distance_km") or 0),
            "duration_min": float(body.get("duration_min") or 0),
            "calories_kcal": float(body.get("calories_kcal") or 0),
            "recorded_at": body.get("recorded_at") or now_iso(),
            "created_at": now_iso(),
        }
        db.execute("INSERT INTO activity_records VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)", tuple(row.values()))
        audit(db, "create_activity", "activity_records", row["id"])
        return row

    def create_sleep(self, db: sqlite3.Connection) -> dict:
        body = self.read_json()
        duration = float(body.get("duration_hours") or 0)
        if duration <= 0:
            raise ValueError("睡眠时长必须大于 0")
        row = {
            "id": str(uuid.uuid4()),
            "user_id": DEMO_USER_ID,
            "duration_hours": duration,
            "deep_sleep_hours": float(body.get("deep_sleep_hours") or 0),
            "wake_count": int(body.get("wake_count") or 0),
            "quality_score": int(body.get("quality_score") or 0),
            "recorded_at": body.get("recorded_at") or now_iso(),
            "created_at": now_iso(),
        }
        db.execute("INSERT INTO sleep_records VALUES (?, ?, ?, ?, ?, ?, ?, ?)", tuple(row.values()))
        record = {
            "id": str(uuid.uuid4()),
            "user_id": DEMO_USER_ID,
            "metric_code": "sleep_hours",
            "value_numeric": duration,
            "note": f"深睡 {row['deep_sleep_hours']} 小时，醒来 {row['wake_count']} 次",
            "source": "sleep_form",
            "measured_at": row["recorded_at"],
            "created_at": now_iso(),
        }
        db.execute("INSERT INTO health_records VALUES (?, ?, ?, ?, ?, ?, ?, ?)", tuple(record.values()))
        evaluate_record(db, record["id"])
        audit(db, "create_sleep", "sleep_records", row["id"])
        return row

    def create_meal(self, db: sqlite3.Connection) -> dict:
        body = self.read_json()
        if not body.get("foods"):
            raise ValueError("饮食内容必填")
        row = {
            "id": str(uuid.uuid4()),
            "user_id": DEMO_USER_ID,
            "meal_type": body.get("meal_type", "正餐"),
            "foods": body["foods"],
            "calories_kcal": float(body.get("calories_kcal") or 0),
            "protein_g": float(body.get("protein_g") or 0),
            "carbs_g": float(body.get("carbs_g") or 0),
            "fat_g": float(body.get("fat_g") or 0),
            "recorded_at": body.get("recorded_at") or now_iso(),
            "created_at": now_iso(),
        }
        db.execute("INSERT INTO meal_records VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)", tuple(row.values()))
        audit(db, "create_meal", "meal_records", row["id"])
        return row

    def create_device(self, db: sqlite3.Connection) -> dict:
        body = self.read_json()
        if not body.get("provider") or not body.get("device_name"):
            raise ValueError("设备来源和设备名称必填")
        row = {
            "id": str(uuid.uuid4()),
            "user_id": DEMO_USER_ID,
            "provider": body["provider"],
            "device_name": body["device_name"],
            "sync_status": body.get("sync_status", "pending"),
            "last_sync_at": body.get("last_sync_at"),
            "enabled": 1 if body.get("enabled", True) else 0,
            "created_at": now_iso(),
        }
        db.execute("INSERT INTO device_sources VALUES (?, ?, ?, ?, ?, ?, ?, ?)", tuple(row.values()))
        audit(db, "create_device", "device_sources", row["id"])
        return row

    def trends(self, db: sqlite3.Connection, query: dict[str, list[str]]) -> dict:
        metric = query.get("metric", ["blood_pressure_systolic"])[0]
        rows = dict_rows(
            db.execute(
                """
                SELECT date(measured_at) AS day, ROUND(AVG(value_numeric), 2) AS value
                FROM health_records
                WHERE user_id = ? AND metric_code = ?
                GROUP BY date(measured_at)
                ORDER BY day
                """,
                (DEMO_USER_ID, metric),
            )
        )
        metric_row = db.execute("SELECT * FROM metric_definitions WHERE code = ?", (metric,)).fetchone()
        return {"metric": dict(metric_row) if metric_row else None, "points": rows}

    def baselines(self, db: sqlite3.Connection) -> list[dict]:
        rows = dict_rows(
            db.execute(
                """
                SELECT b.*, m.name AS metric_name, m.unit, m.category, m.normal_min, m.normal_max
                FROM health_baselines b
                JOIN metric_definitions m ON m.code = b.metric_code
                WHERE b.user_id = ?
                ORDER BY m.category, m.name
                """,
                (DEMO_USER_ID,),
            )
        )
        if not rows:
            rows = rebuild_health_baselines(db, DEMO_USER_ID)
        return rows

    def risks(self, db: sqlite3.Connection) -> list[dict]:
        return dict_rows(
            db.execute(
                """
                SELECT e.*, rr.description
                FROM risk_events e
                JOIN risk_rules rr ON rr.id = e.rule_id
                ORDER BY CASE e.status WHEN 'open' THEN 0 ELSE 1 END, e.created_at DESC
                LIMIT 50
                """
            )
        )

    def risk_timeline(self, db: sqlite3.Connection, path: str) -> list[dict]:
        risk_id = path.removeprefix("/api/v1/risks/").removesuffix("/timeline")
        return dict_rows(
            db.execute(
                "SELECT * FROM risk_event_timeline WHERE event_id = ? ORDER BY created_at",
                (risk_id,),
            )
        )

    def handle_risk(self, db: sqlite3.Connection, path: str) -> dict:
        risk_id = path.removeprefix("/api/v1/risks/").removesuffix("/handle")
        body = self.read_json()
        row = db.execute("SELECT * FROM risk_events WHERE id = ?", (risk_id,)).fetchone()
        if not row:
            raise ValueError("风险事件不存在")
        db.execute(
            "UPDATE risk_events SET status='handled', handled_note=?, handled_at=? WHERE id=?",
            (body.get("handled_note", "已处理并安排复测"), now_iso(), risk_id),
        )
        timeline(db, risk_id, "handled", body.get("handled_note", "已处理并安排复测"), "demo-user")
        audit(db, "handle_risk", "risk_events", risk_id)
        return dict(db.execute("SELECT * FROM risk_events WHERE id = ?", (risk_id,)).fetchone())

    def action_plans(self, db: sqlite3.Connection) -> list[dict]:
        return dict_rows(
            db.execute(
                """
                SELECT p.*, e.level AS risk_level, e.status AS risk_status
                FROM health_action_plans p
                LEFT JOIN risk_events e ON e.id = p.risk_event_id
                WHERE p.user_id = ?
                ORDER BY CASE p.status WHEN 'open' THEN 0 WHEN 'in_progress' THEN 1 ELSE 2 END, p.due_at
                """,
                (DEMO_USER_ID,),
            )
        )

    def complete_action_plan(self, db: sqlite3.Connection, path: str) -> dict:
        plan_id = path.removeprefix("/api/v1/action-plans/").removesuffix("/complete")
        row = db.execute("SELECT * FROM health_action_plans WHERE id = ?", (plan_id,)).fetchone()
        if not row:
            raise ValueError("行动计划不存在")
        db.execute(
            "UPDATE health_action_plans SET status='done', completed_at=? WHERE id=?",
            (now_iso(), plan_id),
        )
        if row["risk_event_id"]:
            timeline(db, row["risk_event_id"], "action_done", f"行动计划已完成：{row['title']}", "demo-user")
        audit(db, "complete_action_plan", "health_action_plans", plan_id)
        return dict(db.execute("SELECT * FROM health_action_plans WHERE id = ?", (plan_id,)).fetchone())

    def read_json(self) -> dict:
        length = int(self.headers.get("Content-Length", "0"))
        if length == 0:
            return {}
        raw = self.rfile.read(length).decode("utf-8")
        return json.loads(raw)

    def json(self, payload, status: HTTPStatus = HTTPStatus.OK) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def serve_static(self, path: str) -> None:
        target = FRONTEND_DIR / (path.strip("/") or "index.html")
        if target.is_dir():
            target = target / "index.html"
        if not target.exists() or not target.resolve().is_relative_to(FRONTEND_DIR.resolve()):
            self.send_error(HTTPStatus.NOT_FOUND, "Not found")
            return
        content_type = mimetypes.guess_type(target.name)[0] or "application/octet-stream"
        if content_type.startswith("text/") or content_type in ("application/javascript",):
            content_type = f"{content_type}; charset=utf-8"
        data = target.read_bytes()
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, fmt: str, *args) -> None:
        print(f"{self.address_string()} - {fmt % args}")


def main() -> None:
    init_db()
    host = os.getenv("HOST", "127.0.0.1")
    port = int(os.getenv("PORT", "8206"))
    server = ThreadingHTTPServer((host, port), AppHandler)
    print(f"个人健康生活网络数据监测与分析系统 running at http://{host}:{port}")
    server.serve_forever()


if __name__ == "__main__":
    main()
