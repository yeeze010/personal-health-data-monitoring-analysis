from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import backend.app as app


class ApiDataTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.original_db_path = app.DB_PATH
        app.DB_PATH = Path(self.temp_dir.name) / "health.db"
        app.init_db()

    def tearDown(self) -> None:
        app.DB_PATH = self.original_db_path
        self.temp_dir.cleanup()

    def test_seed_contains_independent_product_data(self) -> None:
        with app.db_session() as db:
            total_records = db.execute("SELECT COUNT(*) AS c FROM health_records").fetchone()["c"]
            family_count = db.execute("SELECT COUNT(*) AS c FROM family_members").fetchone()["c"]
            device_count = db.execute("SELECT COUNT(*) AS c FROM device_sources").fetchone()["c"]
            checks = db.execute("SELECT COUNT(*) AS c FROM acceptance_checks").fetchone()["c"]
        self.assertGreaterEqual(total_records, 50)
        self.assertGreaterEqual(family_count, 2)
        self.assertGreaterEqual(device_count, 2)
        self.assertGreaterEqual(checks, 5)

    def test_create_record_triggers_risk_event(self) -> None:
        with app.db_session() as db:
            record = {
                "id": "record-test",
                "user_id": app.DEMO_USER_ID,
                "metric_code": "blood_glucose",
                "value_numeric": 12.1,
                "note": "测试",
                "source": "manual",
                "measured_at": "2026-06-02T08:00:00",
                "created_at": app.now_iso(),
            }
            db.execute("INSERT INTO health_records VALUES (?, ?, ?, ?, ?, ?, ?, ?)", tuple(record.values()))
            app.evaluate_record(db, "record-test")
            risk = db.execute("SELECT * FROM risk_events WHERE record_id='record-test'").fetchone()
        self.assertIsNotNone(risk)
        self.assertEqual(risk["level"], "high")

    def test_create_report_includes_lifestyle_summary(self) -> None:
        with app.db_session() as db:
            report = app.create_report(db, app.DEMO_USER_ID, "weekly")
            found = db.execute("SELECT * FROM health_reports WHERE id = ?", (report["id"],)).fetchone()
        self.assertIn("累计步数", report["summary"])
        self.assertIn("平均睡眠", report["summary"])
        self.assertIsNotNone(found)

    def test_personal_baselines_are_persisted(self) -> None:
        with app.db_session() as db:
            baselines = app.rebuild_health_baselines(db, app.DEMO_USER_ID)
            stored = db.execute("SELECT COUNT(*) AS c FROM health_baselines").fetchone()["c"]
        self.assertGreaterEqual(len(baselines), 5)
        self.assertGreaterEqual(stored, 5)
        self.assertIn("个人历史记录", baselines[0]["explanation"])

    def test_existing_open_risks_are_backfilled_with_plans(self) -> None:
        with app.db_session() as db:
            app.ensure_innovation_backfill(db)
            open_risks = db.execute("SELECT COUNT(*) AS c FROM risk_events WHERE status='open'").fetchone()["c"]
            plans = db.execute("SELECT COUNT(*) AS c FROM health_action_plans WHERE status='open'").fetchone()["c"]
        self.assertGreaterEqual(plans, open_risks)

    def test_risk_event_creates_timeline_and_action_plan(self) -> None:
        with app.db_session() as db:
            record = {
                "id": "record-action-plan",
                "user_id": app.DEMO_USER_ID,
                "metric_code": "blood_pressure_systolic",
                "value_numeric": 166,
                "note": "行动计划测试",
                "source": "manual",
                "measured_at": "2026-06-03T08:00:00",
                "created_at": app.now_iso(),
            }
            db.execute("INSERT INTO health_records VALUES (?, ?, ?, ?, ?, ?, ?, ?)", tuple(record.values()))
            app.evaluate_record(db, "record-action-plan")
            risk = db.execute("SELECT * FROM risk_events WHERE record_id='record-action-plan'").fetchone()
            timeline = db.execute("SELECT * FROM risk_event_timeline WHERE event_id=?", (risk["id"],)).fetchall()
            plan = db.execute("SELECT * FROM health_action_plans WHERE risk_event_id=?", (risk["id"],)).fetchone()
        self.assertIsNotNone(risk)
        self.assertGreaterEqual(len(timeline), 1)
        self.assertIsNotNone(plan)
        self.assertEqual(plan["status"], "open")


if __name__ == "__main__":
    unittest.main()
