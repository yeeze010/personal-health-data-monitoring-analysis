from __future__ import annotations

import json
import base64
import binascii
import hashlib
import hmac
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
DB_PATH = Path(os.getenv("HEALTH_DB_PATH", str(ROOT / "data" / "health.db")))
SOFTWARE_NAME = "个人健康生活网络数据监测与分析系统"
DEMO_USER_ID = "u-demo"
TOKEN_TTL_SECONDS = 30 * 60

ROLE_PERMISSIONS = {
    "个人用户": {"health:read", "health:write", "family:manage", "device:manage", "report:read", "report:create"},
    "家庭管理员": {"health:read", "family:manage", "report:read"},
    "被照护成员": {"health:read", "health:write", "report:create"},
    "健康顾问": {"health:read", "report:read"},
    "平台运营": {"device:manage", "report:read", "admin:read"},
    "系统管理员": {"*"},
}


for _permissions in ROLE_PERMISSIONS.values():
    if "admin:read" in _permissions and "*" not in _permissions:
        _permissions.add("health:read")


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


def required_secret(name: str, minimum: int) -> str:
    value = os.getenv(name, "")
    if len(value) < minimum:
        raise RuntimeError(f"{name} 必须配置且长度不少于 {minimum} 个字符")
    return value


def hash_password(password: str, salt: str) -> str:
    return hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt.encode("utf-8"), 210_000, dklen=32).hex()


def encode_part(value: dict) -> str:
    raw = json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


def decode_part(value: str) -> dict:
    padded = value + "=" * (-len(value) % 4)
    return json.loads(base64.urlsafe_b64decode(padded.encode("ascii")).decode("utf-8"))


def sign_token(user: sqlite3.Row) -> tuple[str, str]:
    now = int(datetime.now().timestamp())
    expires_at = now + TOKEN_TTL_SECONDS
    header = encode_part({"alg": "HS256", "typ": "JWT"})
    payload = encode_part({"sub": user["id"], "role": user["role"], "ver": user["token_version"], "iat": now, "exp": expires_at})
    signature = hmac.new(required_secret("JWT_SECRET", 32).encode("utf-8"), f"{header}.{payload}".encode("ascii"), hashlib.sha256).digest()
    encoded_signature = base64.urlsafe_b64encode(signature).rstrip(b"=").decode("ascii")
    return f"{header}.{payload}.{encoded_signature}", datetime.fromtimestamp(expires_at).replace(microsecond=0).isoformat()


def verify_token(token: str) -> dict | None:
    try:
        header, payload, signature = token.split(".")
        expected = hmac.new(required_secret("JWT_SECRET", 32).encode("utf-8"), f"{header}.{payload}".encode("ascii"), hashlib.sha256).digest()
        actual = base64.urlsafe_b64decode((signature + "=" * (-len(signature) % 4)).encode("ascii"))
        canonical_signature = base64.urlsafe_b64encode(actual).rstrip(b"=").decode("ascii")
        token_header = decode_part(header)
        claims = decode_part(payload)
        if (
            token_header.get("alg") != "HS256"
            or token_header.get("typ") != "JWT"
            or not hmac.compare_digest(signature, canonical_signature)
            or not hmac.compare_digest(actual, expected)
            or int(claims.get("exp", 0)) <= int(datetime.now().timestamp())
        ):
            return None
        return claims
    except (ValueError, TypeError, json.JSONDecodeError, UnicodeDecodeError, binascii.Error):
        return None


def public_user(user: sqlite3.Row) -> dict:
    return {
        "id": user["id"],
        "username": user["username"],
        "displayName": user["name"],
        "role": user["role"],
        "permissions": sorted(ROLE_PERMISSIONS.get(user["role"], set())),
    }


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
              created_at TEXT NOT NULL,
              username TEXT,
              password_hash TEXT,
              password_salt TEXT,
              password_algorithm TEXT,
              token_version INTEGER NOT NULL DEFAULT 1,
              subject_user_id TEXT
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
        ensure_column(db, "users", "username", "TEXT")
        ensure_column(db, "users", "password_hash", "TEXT")
        ensure_column(db, "users", "password_salt", "TEXT")
        ensure_column(db, "users", "password_algorithm", "TEXT")
        ensure_column(db, "users", "token_version", "INTEGER NOT NULL DEFAULT 1")
        ensure_column(db, "users", "subject_user_id", "TEXT")
        ensure_column(db, "metric_definitions", "category", "TEXT DEFAULT '体征'")
        if not db.execute("SELECT 1 FROM users LIMIT 1").fetchone():
            seed(db)
        ensure_auth_users(db)
        db.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_users_username ON users(username)")
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


def ensure_auth_users(db: sqlite3.Connection) -> None:
    personal_password = required_secret("BOOTSTRAP_USER_PASSWORD", 12)
    admin_password = required_secret("BOOTSTRAP_ADMIN_PASSWORD", 12)
    personal_username = os.getenv("BOOTSTRAP_USER_USERNAME", "personal.user").strip()
    admin_username = os.getenv("BOOTSTRAP_ADMIN_USERNAME", "system.admin").strip()
    if not personal_username or not admin_username:
        raise RuntimeError("启动账号用户名不能为空")

    personal = db.execute("SELECT * FROM users WHERE id=?", (DEMO_USER_ID,)).fetchone()
    if personal and personal["password_algorithm"] != "pbkdf2-sha256-210000":
        salt = os.urandom(16).hex()
        db.execute(
            """
            UPDATE users SET username=?, password_hash=?, password_salt=?, password_algorithm=?,
                             token_version=COALESCE(token_version, 1), subject_user_id=?
            WHERE id=?
            """,
            (personal_username, hash_password(personal_password, salt), salt, "pbkdf2-sha256-210000", DEMO_USER_ID, DEMO_USER_ID),
        )

    admin = db.execute("SELECT * FROM users WHERE id='u-admin'").fetchone()
    if not admin:
        salt = os.urandom(16).hex()
        db.execute(
            """
            INSERT INTO users(id, name, email, role, status, created_at, username, password_hash,
                              password_salt, password_algorithm, token_version, subject_user_id)
            VALUES (?, ?, ?, ?, 'active', ?, ?, ?, ?, 'pbkdf2-sha256-210000', 1, ?)
            """,
            ("u-admin", "系统管理员", "admin@localhost", "系统管理员", now_iso(), admin_username, hash_password(admin_password, salt), salt, DEMO_USER_ID),
        )
    elif admin["password_algorithm"] != "pbkdf2-sha256-210000":
        salt = os.urandom(16).hex()
        db.execute(
            """
            UPDATE users SET username=?, password_hash=?, password_salt=?, password_algorithm=?,
                             token_version=COALESCE(token_version, 1), subject_user_id=?
            WHERE id='u-admin'
            """,
            (admin_username, hash_password(admin_password, salt), salt, "pbkdf2-sha256-210000", DEMO_USER_ID),
        )

    role_accounts = [
        ("u-family-admin", "家庭管理员", "family.admin", "BOOTSTRAP_FAMILY_PASSWORD", personal_password),
        ("u-cared-member", "被照护成员", "cared.member", "BOOTSTRAP_CARED_PASSWORD", personal_password),
        ("u-health-advisor", "健康顾问", "health.advisor", "BOOTSTRAP_ADVISOR_PASSWORD", personal_password),
        ("u-platform-operator", "平台运营", "platform.operator", "BOOTSTRAP_OPERATOR_PASSWORD", personal_password),
    ]
    for user_id, name, username, password_env, fallback_password in role_accounts:
        password = os.getenv(password_env, fallback_password)
        existing = db.execute("SELECT * FROM users WHERE id=?", (user_id,)).fetchone()
        if not existing:
            salt = os.urandom(16).hex()
            db.execute(
                """
                INSERT INTO users(id, name, email, role, status, created_at, username, password_hash,
                                  password_salt, password_algorithm, token_version, subject_user_id)
                VALUES (?, ?, ?, ?, 'active', ?, ?, ?, ?, 'pbkdf2-sha256-210000', 1, ?)
                """,
                (user_id, name, f"{username}@localhost", name, now_iso(), username, hash_password(password, salt), salt, DEMO_USER_ID),
            )
        elif existing["password_algorithm"] != "pbkdf2-sha256-210000" or existing["username"] != username:
            salt = os.urandom(16).hex()
            db.execute(
                """
                UPDATE users SET username=?, password_hash=?, password_salt=?, password_algorithm=?,
                                 token_version=COALESCE(token_version, 1), subject_user_id=?, role=?, name=?
                WHERE id=?
                """,
                (username, hash_password(password, salt), salt, "pbkdf2-sha256-210000", DEMO_USER_ID, name, name, user_id),
            )


def seed(db: sqlite3.Connection) -> None:
    db.execute(
        "INSERT INTO users(id, name, email, role, status, created_at) VALUES (?, ?, ?, ?, ?, ?)",
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


def audit(db: sqlite3.Connection, action: str, resource_type: str, resource_id: str | None = None, actor: str = "system") -> None:
    db.execute(
        "INSERT INTO audit_logs VALUES (?, ?, ?, ?, ?, ?)",
        (str(uuid.uuid4()), actor, action, resource_type, resource_id, now_iso()),
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


class RequestError(Exception):
    def __init__(self, status: HTTPStatus, message: str):
        super().__init__(message)
        self.status = status


class AppHandler(BaseHTTPRequestHandler):
    server_version = "PersonalHealthMonitor/2.0"

    def do_OPTIONS(self) -> None:
        self.send_response(HTTPStatus.NO_CONTENT)
        self.write_cors_headers()
        self.send_header("Access-Control-Allow-Methods", "GET, POST, PUT, PATCH, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Authorization, Content-Type")
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
                public_request = (method == "GET" and path == "/api/v1/health") or (method == "POST" and path == "/api/v1/auth/login")
                if not public_request:
                    user = self.authenticate(db)
                    self.current_user = user
                    self.subject_user_id = user["subject_user_id"] or user["id"]
                    self.require_permission(user, self.permission_for(method, path))
                if method == "GET" and path == "/api/v1/health":
                    self.json({"status": "ok", "service": f"{SOFTWARE_NAME} API", "time": now_iso()})
                elif method == "POST" and path == "/api/v1/auth/login":
                    self.json(self.login(db))
                elif method == "GET" and path == "/api/v1/auth/me":
                    self.json(public_user(self.current_user))
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
                    self.json(rebuild_health_baselines(db, self.subject_user_id), HTTPStatus.CREATED)
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
                elif method == "GET" and path.startswith("/api/v1/reports/") and path.endswith("/download"):
                    self.download_report(db, path)
                elif method == "GET" and path == "/api/v1/reports":
                    self.json(dict_rows(db.execute("SELECT * FROM health_reports WHERE user_id=? ORDER BY created_at DESC", (self.subject_user_id,))))
                elif method == "POST" and path == "/api/v1/reports":
                    body = self.read_json()
                    self.json(create_report(db, self.subject_user_id, body.get("report_type", "weekly")), HTTPStatus.CREATED)
                elif method == "GET" and path == "/api/v1/family/members":
                    self.json(dict_rows(db.execute("SELECT * FROM family_members WHERE owner_user_id=? ORDER BY created_at DESC", (self.subject_user_id,))))
                elif method == "POST" and path == "/api/v1/family/members":
                    self.json(self.create_family_member(db), HTTPStatus.CREATED)
                elif method == "PATCH" and path.startswith("/api/v1/family/members/") and path.endswith("/revoke"):
                    self.json(self.revoke_family_member(db, path))
                elif method == "GET" and path == "/api/v1/privacy/authorizations":
                    self.json(dict_rows(db.execute("SELECT * FROM privacy_authorizations WHERE grantor_user_id=? ORDER BY created_at DESC", (self.subject_user_id,))))
                elif method == "PATCH" and path.startswith("/api/v1/privacy/authorizations/") and path.endswith("/revoke"):
                    self.json(self.revoke_privacy_authorization(db, path))
                elif method == "GET" and path == "/api/v1/lifestyle/activity":
                    self.json(dict_rows(db.execute("SELECT * FROM activity_records WHERE user_id=? ORDER BY recorded_at DESC LIMIT 30", (self.subject_user_id,))))
                elif method == "POST" and path == "/api/v1/lifestyle/activity":
                    self.json(self.create_activity(db), HTTPStatus.CREATED)
                elif method == "GET" and path == "/api/v1/lifestyle/sleep":
                    self.json(dict_rows(db.execute("SELECT * FROM sleep_records WHERE user_id=? ORDER BY recorded_at DESC LIMIT 30", (self.subject_user_id,))))
                elif method == "POST" and path == "/api/v1/lifestyle/sleep":
                    self.json(self.create_sleep(db), HTTPStatus.CREATED)
                elif method == "GET" and path == "/api/v1/lifestyle/meals":
                    self.json(dict_rows(db.execute("SELECT * FROM meal_records WHERE user_id=? ORDER BY recorded_at DESC LIMIT 30", (self.subject_user_id,))))
                elif method == "POST" and path == "/api/v1/lifestyle/meals":
                    self.json(self.create_meal(db), HTTPStatus.CREATED)
                elif method == "GET" and path == "/api/v1/devices":
                    self.json(dict_rows(db.execute("SELECT * FROM device_sources WHERE user_id=? ORDER BY created_at DESC", (self.subject_user_id,))))
                elif method == "POST" and path == "/api/v1/devices":
                    self.json(self.create_device(db), HTTPStatus.CREATED)
                elif method == "GET" and path == "/api/v1/files":
                    self.json(dict_rows(db.execute("SELECT * FROM files WHERE owner_user_id=? ORDER BY created_at DESC", (self.subject_user_id,))))
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
        except RequestError as exc:
            self.json({"message": str(exc)}, exc.status)
        except ValueError as exc:
            self.json({"message": str(exc)}, HTTPStatus.BAD_REQUEST)
        except Exception as exc:
            self.json({"message": "服务器处理失败", "detail": str(exc)}, HTTPStatus.INTERNAL_SERVER_ERROR)

    def permission_for(self, method: str, path: str) -> str:
        if path.startswith("/api/v1/admin/"):
            return "admin:read"
        if method == "POST" and path == "/api/v1/family/members":
            return "family:manage"
        if method == "PATCH" and (
            (path.startswith("/api/v1/family/members/") and path.endswith("/revoke"))
            or (path.startswith("/api/v1/privacy/authorizations/") and path.endswith("/revoke"))
        ):
            return "family:manage"
        if method == "POST" and path == "/api/v1/devices":
            return "device:manage"
        if method == "POST" and path == "/api/v1/reports":
            return "report:create"
        if method in {"POST", "PUT", "PATCH"}:
            return "health:write"
        return "health:read"

    def require_permission(self, user: sqlite3.Row, permission: str) -> None:
        permissions = ROLE_PERMISSIONS.get(user["role"], set())
        if "*" not in permissions and permission not in permissions:
            raise RequestError(HTTPStatus.FORBIDDEN, "当前角色没有执行此操作的权限")

    def authenticate(self, db: sqlite3.Connection) -> sqlite3.Row:
        header = self.headers.get("Authorization", "")
        token = header.removeprefix("Bearer ") if header.startswith("Bearer ") else ""
        claims = verify_token(token) if token else None
        if not claims:
            raise RequestError(HTTPStatus.UNAUTHORIZED, "请先登录或重新登录")
        user = db.execute("SELECT * FROM users WHERE id=? AND status='active'", (claims.get("sub"),)).fetchone()
        if not user or int(user["token_version"] or 0) != int(claims.get("ver", -1)) or user["role"] != claims.get("role"):
            raise RequestError(HTTPStatus.UNAUTHORIZED, "登录状态已失效")
        return user

    def login(self, db: sqlite3.Connection) -> dict:
        body = self.read_json()
        username = str(body.get("username", "")).strip()
        password = str(body.get("password", ""))
        role = str(body.get("role", "")).strip()
        user = db.execute("SELECT * FROM users WHERE username=? AND status='active'", (username,)).fetchone()
        valid = bool(user and user["password_salt"] and hmac.compare_digest(hash_password(password, user["password_salt"]), user["password_hash"] or ""))
        if not valid or user["role"] != role:
            raise RequestError(HTTPStatus.UNAUTHORIZED, "角色、用户名或密码不匹配")
        token, expires_at = sign_token(user)
        audit(db, "auth_login", "users", user["id"], user["username"])
        return {"accessToken": token, "expiresAt": expires_at, "user": public_user(user)}

    def profile(self, db: sqlite3.Connection) -> dict:
        row = db.execute(
            """
            SELECT u.id, u.name, u.email, u.role, p.gender, p.birthday, p.height_cm,
                   p.blood_type, p.medical_history, p.updated_at
            FROM users u
            JOIN health_profiles p ON p.user_id = u.id
            WHERE u.id = ?
            """,
            (self.subject_user_id,),
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
            (*values.values(), now_iso(), self.subject_user_id),
        )
        audit(db, "update_profile", "health_profiles", self.subject_user_id, self.current_user["username"])
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
                (self.subject_user_id, self.subject_user_id),
            )
        )
        open_risks = db.execute("SELECT COUNT(*) AS c FROM risk_events WHERE user_id=? AND status='open'", (self.subject_user_id,)).fetchone()["c"]
        total_records = db.execute("SELECT COUNT(*) AS c FROM health_records WHERE user_id=?", (self.subject_user_id,)).fetchone()["c"]
        report_count = db.execute("SELECT COUNT(*) AS c FROM health_reports WHERE user_id=?", (self.subject_user_id,)).fetchone()["c"]
        family_count = db.execute("SELECT COUNT(*) AS c FROM family_members WHERE owner_user_id=? AND status='active'", (self.subject_user_id,)).fetchone()["c"]
        device_count = db.execute("SELECT COUNT(*) AS c FROM device_sources WHERE user_id=? AND enabled=1", (self.subject_user_id,)).fetchone()["c"]
        weekly_steps = db.execute(
            "SELECT COALESCE(SUM(steps), 0) AS c FROM activity_records WHERE user_id=? AND recorded_at >= ?",
            (self.subject_user_id, (datetime.now() - timedelta(days=7)).isoformat()),
        ).fetchone()["c"]
        avg_sleep = db.execute(
            "SELECT ROUND(AVG(duration_hours), 1) AS c FROM sleep_records WHERE user_id=? AND recorded_at >= ?",
            (self.subject_user_id, (datetime.now() - timedelta(days=7)).isoformat()),
        ).fetchone()["c"]
        meal_calories = db.execute(
            "SELECT COALESCE(SUM(calories_kcal), 0) AS c FROM meal_records WHERE user_id=? AND date(recorded_at)=date('now')",
            (self.subject_user_id,),
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
        params: list[str] = [self.subject_user_id]
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
            "user_id": self.subject_user_id,
            "metric_code": metric_code,
            "value_numeric": float(value),
            "note": body.get("note", ""),
            "source": body.get("source", "manual"),
            "measured_at": body.get("measured_at") or now_iso(),
            "created_at": now_iso(),
        }
        db.execute("INSERT INTO health_records VALUES (?, ?, ?, ?, ?, ?, ?, ?)", tuple(record.values()))
        evaluate_record(db, record["id"])
        rebuild_health_baselines(db, self.subject_user_id)
        audit(db, "create_record", "health_records", record["id"])
        return record

    def create_family_member(self, db: sqlite3.Connection) -> dict:
        body = self.read_json()
        if not body.get("member_name") or not body.get("relation"):
            raise ValueError("成员姓名和关系必填")
        row = {
            "id": str(uuid.uuid4()),
            "owner_user_id": self.subject_user_id,
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

    def revoke_family_member(self, db: sqlite3.Connection, path: str) -> dict:
        member_id = path.removeprefix("/api/v1/family/members/").removesuffix("/revoke")
        row = db.execute(
            "SELECT * FROM family_members WHERE id=? AND owner_user_id=?",
            (member_id, self.subject_user_id),
        ).fetchone()
        if not row:
            raise RequestError(HTTPStatus.NOT_FOUND, "家庭成员不存在")
        db.execute(
            "UPDATE family_members SET status='revoked', alert_enabled=0 WHERE id=?",
            (member_id,),
        )
        db.execute(
            "UPDATE privacy_authorizations SET status='revoked' WHERE grantor_user_id=? AND grantee_name=?",
            (self.subject_user_id, row["member_name"]),
        )
        audit(db, "revoke_family_member", "family_members", member_id, self.current_user["username"])
        return dict(db.execute("SELECT * FROM family_members WHERE id=?", (member_id,)).fetchone())

    def revoke_privacy_authorization(self, db: sqlite3.Connection, path: str) -> dict:
        authorization_id = path.removeprefix("/api/v1/privacy/authorizations/").removesuffix("/revoke")
        row = db.execute(
            "SELECT * FROM privacy_authorizations WHERE id=? AND grantor_user_id=?",
            (authorization_id, self.subject_user_id),
        ).fetchone()
        if not row:
            raise RequestError(HTTPStatus.NOT_FOUND, "隐私授权不存在")
        db.execute("UPDATE privacy_authorizations SET status='revoked' WHERE id=?", (authorization_id,))
        audit(db, "revoke_privacy_authorization", "privacy_authorizations", authorization_id, self.current_user["username"])
        return dict(db.execute("SELECT * FROM privacy_authorizations WHERE id=?", (authorization_id,)).fetchone())

    def download_report(self, db: sqlite3.Connection, path: str) -> None:
        report_id = path.removeprefix("/api/v1/reports/").removesuffix("/download")
        report = db.execute(
            "SELECT * FROM health_reports WHERE id=? AND user_id=?",
            (report_id, self.subject_user_id),
        ).fetchone()
        if not report:
            raise RequestError(HTTPStatus.NOT_FOUND, "健康报告不存在")
        payload = json.dumps(dict(report), ensure_ascii=False, indent=2).encode("utf-8")
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Disposition", f'attachment; filename="health-report-{report_id}.json"')
        self.write_cors_headers()
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)
        audit(db, "download_report", "health_reports", report_id, self.current_user["username"])

    def create_activity(self, db: sqlite3.Connection) -> dict:
        body = self.read_json()
        row = {
            "id": str(uuid.uuid4()),
            "user_id": self.subject_user_id,
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
            "user_id": self.subject_user_id,
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
            "user_id": self.subject_user_id,
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
            "user_id": self.subject_user_id,
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
            "user_id": self.subject_user_id,
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
                (self.subject_user_id, metric),
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
                (self.subject_user_id,),
            )
        )
        if not rows:
            rows = rebuild_health_baselines(db, self.subject_user_id)
        return rows

    def risks(self, db: sqlite3.Connection) -> list[dict]:
        return dict_rows(
            db.execute(
                """
                SELECT e.*, rr.description
                FROM risk_events e
                JOIN risk_rules rr ON rr.id = e.rule_id
                WHERE e.user_id = ?
                ORDER BY CASE e.status WHEN 'open' THEN 0 ELSE 1 END, e.created_at DESC
                LIMIT 50
                """,
                (self.subject_user_id,),
            )
        )

    def risk_timeline(self, db: sqlite3.Connection, path: str) -> list[dict]:
        risk_id = path.removeprefix("/api/v1/risks/").removesuffix("/timeline")
        return dict_rows(
            db.execute(
                """
                SELECT t.* FROM risk_event_timeline t
                JOIN risk_events e ON e.id=t.event_id
                WHERE t.event_id=? AND e.user_id=? ORDER BY t.created_at
                """,
                (risk_id, self.subject_user_id),
            )
        )

    def handle_risk(self, db: sqlite3.Connection, path: str) -> dict:
        risk_id = path.removeprefix("/api/v1/risks/").removesuffix("/handle")
        body = self.read_json()
        row = db.execute("SELECT * FROM risk_events WHERE id = ? AND user_id=?", (risk_id, self.subject_user_id)).fetchone()
        if not row:
            raise ValueError("风险事件不存在")
        db.execute(
            "UPDATE risk_events SET status='handled', handled_note=?, handled_at=? WHERE id=?",
            (body.get("handled_note", "已处理并安排复测"), now_iso(), risk_id),
        )
        timeline(db, risk_id, "handled", body.get("handled_note", "已处理并安排复测"), self.current_user["username"])
        audit(db, "handle_risk", "risk_events", risk_id, self.current_user["username"])
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
                (self.subject_user_id,),
            )
        )

    def complete_action_plan(self, db: sqlite3.Connection, path: str) -> dict:
        plan_id = path.removeprefix("/api/v1/action-plans/").removesuffix("/complete")
        row = db.execute("SELECT * FROM health_action_plans WHERE id = ? AND user_id=?", (plan_id, self.subject_user_id)).fetchone()
        if not row:
            raise ValueError("行动计划不存在")
        db.execute(
            "UPDATE health_action_plans SET status='done', completed_at=? WHERE id=?",
            (now_iso(), plan_id),
        )
        if row["risk_event_id"]:
            timeline(db, row["risk_event_id"], "action_done", f"行动计划已完成：{row['title']}", self.current_user["username"])
        audit(db, "complete_action_plan", "health_action_plans", plan_id, self.current_user["username"])
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
        self.write_cors_headers()
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def write_cors_headers(self) -> None:
        origin = self.headers.get("Origin", "")
        allowed = {item.strip() for item in os.getenv("ALLOWED_ORIGINS", "http://127.0.0.1:5206,http://localhost:5206").split(",") if item.strip()}
        if origin in allowed:
            self.send_header("Access-Control-Allow-Origin", origin)
            self.send_header("Vary", "Origin")

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
    print(f"{SOFTWARE_NAME} API running at http://{host}:{port}")
    server.serve_forever()


if __name__ == "__main__":
    main()
