from __future__ import annotations

import json
import os
import socket
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PYTHON = sys.executable


def free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def request_json(url: str, method: str = "GET", payload: dict | None = None, token: str = "") -> dict | list:
    data = None
    headers = {}
    if payload is not None:
        data = json.dumps(payload).encode("utf-8")
        headers["Content-Type"] = "application/json"
    if token:
        headers["Authorization"] = f"Bearer {token}"
    req = urllib.request.Request(url, data=data, method=method, headers=headers)
    with urllib.request.urlopen(req, timeout=8) as resp:
        return json.loads(resp.read().decode("utf-8"))


def request_text(url: str) -> str:
    with urllib.request.urlopen(url, timeout=8) as resp:
        return resp.read().decode("utf-8")


def request_download(url: str, token: str) -> tuple[dict[str, str], bytes]:
    req = urllib.request.Request(url, headers={"Authorization": f"Bearer {token}"})
    with urllib.request.urlopen(req, timeout=8) as resp:
        return dict(resp.headers.items()), resp.read()


def wait_for_server(base_url: str) -> None:
    deadline = time.time() + 15
    last_error: Exception | None = None
    while time.time() < deadline:
        try:
            health = request_json(f"{base_url}/api/v1/health")
            if (
                isinstance(health, dict)
                and health.get("status") == "ok"
                and health.get("service") == "个人健康生活网络数据监测与分析系统 API"
            ):
                return
        except (OSError, urllib.error.URLError) as exc:
            last_error = exc
            time.sleep(0.3)
    raise RuntimeError(f"服务启动超时：{last_error}")


def main() -> None:
    port = free_port()
    base_url = f"http://127.0.0.1:{port}"
    env = os.environ.copy()
    env["PORT"] = str(port)
    env["HOST"] = "127.0.0.1"
    env["BOOTSTRAP_USER_PASSWORD"] = "Test_User_Password_2026!"
    env["BOOTSTRAP_ADMIN_PASSWORD"] = "Test_Admin_Password_2026!"
    env["JWT_SECRET"] = "test-jwt-secret-with-at-least-32-characters"
    temp_dir = tempfile.TemporaryDirectory()
    env["HEALTH_DB_PATH"] = str(Path(temp_dir.name) / "health-smoke.db")
    proc = subprocess.Popen(
        [PYTHON, "backend/app.py"],
        cwd=ROOT,
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
    )
    try:
        wait_for_server(base_url)
        html = request_text(base_url)
        assert "个人健康生活网络数据监测与分析系统" in html
        assert "设备连接" in html

        try:
            request_json(f"{base_url}/api/v1/summary")
            raise AssertionError("未登录访问应被拒绝")
        except urllib.error.HTTPError as exc:
            assert exc.code == 401

        login = request_json(
            f"{base_url}/api/v1/auth/login",
            "POST",
            {"role": "个人用户", "username": "personal.user", "password": env["BOOTSTRAP_USER_PASSWORD"]},
        )
        token = login["accessToken"]
        assert login["user"]["role"] == "个人用户"

        profile = request_json(f"{base_url}/api/v1/auth/me", token=token)
        assert profile["username"] == "personal.user"

        for role, username in [
            ("家庭管理员", "family.admin"),
            ("被照护成员", "cared.member"),
            ("健康顾问", "health.advisor"),
            ("平台运营", "platform.operator"),
            ("系统管理员", "system.admin"),
        ]:
            role_password = env["BOOTSTRAP_ADMIN_PASSWORD"] if role == "系统管理员" else env["BOOTSTRAP_USER_PASSWORD"]
            role_login = request_json(
                f"{base_url}/api/v1/auth/login",
                "POST",
                {"role": role, "username": username, "password": role_password},
            )
            assert role_login["user"]["role"] == role

        blueprint = request_json(f"{base_url}/api/v1/product/blueprint", token=token)
        assert "个人档案" in blueprint["modules"]

        metrics = request_json(f"{base_url}/api/v1/metrics", token=token)
        assert isinstance(metrics, list) and len(metrics) >= 7

        summary = request_json(f"{base_url}/api/v1/summary", token=token)
        assert summary["kpis"]["total_records"] > 0
        assert summary["kpis"]["family_count"] >= 2

        record = request_json(
            f"{base_url}/api/v1/records",
            "POST",
            {"metric_code": "blood_glucose", "value_numeric": 10.2, "note": "冒烟测试"},
            token,
        )
        assert record["metric_code"] == "blood_glucose"

        activity = request_json(
            f"{base_url}/api/v1/lifestyle/activity",
            "POST",
            {"activity_type": "慢跑", "steps": 9000, "distance_km": 6.2, "duration_min": 52},
            token,
        )
        assert activity["steps"] == 9000

        sleep = request_json(
            f"{base_url}/api/v1/lifestyle/sleep",
            "POST",
            {"duration_hours": 5.2, "deep_sleep_hours": 1.0, "wake_count": 4, "quality_score": 62},
            token,
        )
        assert sleep["duration_hours"] == 5.2

        meal = request_json(
            f"{base_url}/api/v1/lifestyle/meals",
            "POST",
            {"meal_type": "晚餐", "foods": "清蒸鱼、杂蔬", "calories_kcal": 580},
            token,
        )
        assert "清蒸鱼" in meal["foods"]

        family = request_json(
            f"{base_url}/api/v1/family/members",
            "POST",
            {"member_name": "测试家属", "relation": "姐姐", "age": 36, "authorization_scope": "异常提醒"},
            token,
        )
        assert family["member_name"] == "测试家属"

        revoked_family = request_json(
            f"{base_url}/api/v1/family/members/{family['id']}/revoke",
            "PATCH",
            token=token,
        )
        assert revoked_family["status"] == "revoked"

        device = request_json(
            f"{base_url}/api/v1/devices",
            "POST",
            {"provider": "Test Provider", "device_name": "Test Band", "sync_status": "pending"},
            token,
        )
        assert device["device_name"] == "Test Band"

        risks = request_json(f"{base_url}/api/v1/risks", token=token)
        open_risk = next(risk for risk in risks if risk["status"] == "open")
        handled = request_json(
            f"{base_url}/api/v1/risks/{open_risk['id']}/handle",
            "PATCH",
            {"handled_note": "冒烟测试闭环"},
            token,
        )
        assert handled["status"] == "handled"

        report = request_json(f"{base_url}/api/v1/reports", "POST", {"report_type": "weekly"}, token)
        assert "累计步数" in report["summary"]

        headers, report_body = request_download(f"{base_url}/api/v1/reports/{report['id']}/download", token)
        assert "attachment" in headers.get("Content-Disposition", "")
        assert report["id"].encode("utf-8") in report_body

        files = request_json(f"{base_url}/api/v1/files", token=token)
        checks = request_json(f"{base_url}/api/v1/acceptance/checks", token=token)
        privacy = request_json(f"{base_url}/api/v1/privacy/authorizations", token=token)
        assert files and checks and privacy

        privacy_target = next(item for item in privacy if item["status"] == "active")
        revoked_privacy = request_json(
            f"{base_url}/api/v1/privacy/authorizations/{privacy_target['id']}/revoke",
            "PATCH",
            token=token,
        )
        assert revoked_privacy["status"] == "revoked"

        try:
            request_json(f"{base_url}/api/v1/admin/users", token=token)
            raise AssertionError("个人用户不应访问管理接口")
        except urllib.error.HTTPError as exc:
            assert exc.code == 403

        print(f"smoke ok: {base_url}")
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()
        stderr = proc.stderr.read() if proc.stderr else ""
        if proc.returncode not in (0, -15, 1) and stderr:
            print(stderr)
        temp_dir.cleanup()


if __name__ == "__main__":
    main()
