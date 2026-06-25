from __future__ import annotations

import json
import os
import socket
import subprocess
import sys
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


def request_json(url: str, method: str = "GET", payload: dict | None = None) -> dict | list:
    data = None
    headers = {}
    if payload is not None:
        data = json.dumps(payload).encode("utf-8")
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=data, method=method, headers=headers)
    with urllib.request.urlopen(req, timeout=8) as resp:
        return json.loads(resp.read().decode("utf-8"))


def request_text(url: str) -> str:
    with urllib.request.urlopen(url, timeout=8) as resp:
        return resp.read().decode("utf-8")


def wait_for_server(base_url: str) -> None:
    deadline = time.time() + 15
    last_error: Exception | None = None
    while time.time() < deadline:
        try:
            health = request_json(f"{base_url}/api/v1/health")
            if isinstance(health, dict) and health.get("status") == "ok":
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
        assert "个人健康数据监测分析平台" in html
        assert "验收中心" in html

        blueprint = request_json(f"{base_url}/api/v1/product/blueprint")
        assert "个人档案" in blueprint["modules"]

        metrics = request_json(f"{base_url}/api/v1/metrics")
        assert isinstance(metrics, list) and len(metrics) >= 7

        summary = request_json(f"{base_url}/api/v1/summary")
        assert summary["kpis"]["total_records"] > 0
        assert summary["kpis"]["family_count"] >= 2

        record = request_json(
            f"{base_url}/api/v1/records",
            "POST",
            {"metric_code": "blood_glucose", "value_numeric": 10.2, "note": "冒烟测试"},
        )
        assert record["metric_code"] == "blood_glucose"

        activity = request_json(
            f"{base_url}/api/v1/lifestyle/activity",
            "POST",
            {"activity_type": "慢跑", "steps": 9000, "distance_km": 6.2, "duration_min": 52},
        )
        assert activity["steps"] == 9000

        sleep = request_json(
            f"{base_url}/api/v1/lifestyle/sleep",
            "POST",
            {"duration_hours": 5.2, "deep_sleep_hours": 1.0, "wake_count": 4, "quality_score": 62},
        )
        assert sleep["duration_hours"] == 5.2

        meal = request_json(
            f"{base_url}/api/v1/lifestyle/meals",
            "POST",
            {"meal_type": "晚餐", "foods": "清蒸鱼、杂蔬", "calories_kcal": 580},
        )
        assert "清蒸鱼" in meal["foods"]

        family = request_json(
            f"{base_url}/api/v1/family/members",
            "POST",
            {"member_name": "测试家属", "relation": "姐姐", "age": 36, "authorization_scope": "异常提醒"},
        )
        assert family["member_name"] == "测试家属"

        device = request_json(
            f"{base_url}/api/v1/devices",
            "POST",
            {"provider": "Test Provider", "device_name": "Test Band", "sync_status": "pending"},
        )
        assert device["device_name"] == "Test Band"

        risks = request_json(f"{base_url}/api/v1/risks")
        open_risk = next(risk for risk in risks if risk["status"] == "open")
        handled = request_json(
            f"{base_url}/api/v1/risks/{open_risk['id']}/handle",
            "PATCH",
            {"handled_note": "冒烟测试闭环"},
        )
        assert handled["status"] == "handled"

        report = request_json(f"{base_url}/api/v1/reports", "POST", {"report_type": "weekly"})
        assert "累计步数" in report["summary"]

        files = request_json(f"{base_url}/api/v1/files")
        checks = request_json(f"{base_url}/api/v1/acceptance/checks")
        privacy = request_json(f"{base_url}/api/v1/privacy/authorizations")
        assert files and checks and privacy

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


if __name__ == "__main__":
    main()
