from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from statistics import mean, pstdev
from typing import Iterable


@dataclass(frozen=True)
class HealthReading:
    metric: str
    value: float
    measured_at: datetime
    source: str = "manual"


@dataclass(frozen=True)
class RiskSignal:
    metric: str
    level: str
    score: int
    message: str
    evidence: tuple[str, ...]


REFERENCE_RANGES = {
    "heart_rate": (55.0, 100.0),
    "blood_glucose": (3.9, 7.8),
    "systolic": (90.0, 139.0),
    "diastolic": (60.0, 89.0),
    "sleep_hours": (6.0, 9.0),
    "spo2": (95.0, 100.0),
    "steps": (6000.0, 30000.0),
}


def group_readings(readings: Iterable[HealthReading]) -> dict[str, list[HealthReading]]:
    grouped: dict[str, list[HealthReading]] = {}
    for reading in readings:
        grouped.setdefault(reading.metric, []).append(reading)
    for values in grouped.values():
        values.sort(key=lambda item: item.measured_at)
    return grouped


def calculate_trend(readings: list[HealthReading]) -> float:
    if len(readings) < 2:
        return 0.0
    xs = list(range(len(readings)))
    x_mean = mean(xs)
    y_mean = mean(item.value for item in readings)
    denominator = sum((x - x_mean) ** 2 for x in xs)
    if denominator == 0:
        return 0.0
    return sum((x - x_mean) * (reading.value - y_mean) for x, reading in zip(xs, readings)) / denominator


def detect_metric_risk(metric: str, readings: list[HealthReading]) -> RiskSignal | None:
    if not readings or metric not in REFERENCE_RANGES:
        return None
    low, high = REFERENCE_RANGES[metric]
    recent = readings[-7:]
    latest = recent[-1].value
    average = mean(item.value for item in recent)
    trend = calculate_trend(recent)
    evidence: list[str] = [f"latest={latest:.2f}", f"average={average:.2f}", f"trend={trend:.3f}"]
    score = 0
    if latest < low or latest > high:
        score += 45
        evidence.append("latest-out-of-range")
    outliers = [item for item in recent if item.value < low or item.value > high]
    if len(outliers) >= 3:
        score += 30
        evidence.append("repeated-out-of-range")
    width = max(high - low, 1.0)
    if abs(trend) > width * 0.08:
        score += 15
        evidence.append("rapid-trend")
    values = [item.value for item in recent]
    if len(values) >= 4 and pstdev(values) > width * 0.25:
        score += 10
        evidence.append("high-variation")
    if score == 0:
        return None
    level = "high" if score >= 70 else "medium" if score >= 40 else "low"
    return RiskSignal(metric, level, min(score, 100), f"{metric}存在{level}级健康风险", tuple(evidence))


def assess_health_risks(readings: Iterable[HealthReading]) -> list[RiskSignal]:
    signals = [
        signal
        for metric, metric_readings in group_readings(readings).items()
        if (signal := detect_metric_risk(metric, metric_readings)) is not None
    ]
    return sorted(signals, key=lambda signal: signal.score, reverse=True)


def build_health_recommendations(signals: list[RiskSignal]) -> list[dict[str, str]]:
    recommendations: list[dict[str, str]] = []
    for signal in signals:
        if signal.metric in {"systolic", "diastolic"}:
            action = "连续静息测量血压并记录，若持续异常请咨询专业医疗人员"
        elif signal.metric == "blood_glucose":
            action = "复核测量时段与饮食记录，持续异常时及时就医"
        elif signal.metric == "heart_rate":
            action = "减少高强度活动并进行静息复测，伴随不适时及时就医"
        elif signal.metric == "spo2":
            action = "确认设备佩戴正确并立即复测，持续偏低时及时就医"
        elif signal.metric == "sleep_hours":
            action = "固定作息并减少睡前刺激，连续两周观察改善情况"
        elif signal.metric == "steps":
            action = "结合身体状态逐步增加日常活动量"
        else:
            action = "持续观察并补充记录"
        recommendations.append({
            "metric": signal.metric,
            "priority": signal.level,
            "action": action,
            "reason": signal.message,
        })
    return recommendations


def calculate_data_completeness(
    readings: Iterable[HealthReading],
    required_metrics: set[str],
    days: int = 7,
    now: datetime | None = None,
) -> dict[str, object]:
    current = now or datetime.now()
    cutoff = current - timedelta(days=days)
    grouped = group_readings(item for item in readings if item.measured_at >= cutoff)
    coverage = {
        metric: min(1.0, len(grouped.get(metric, [])) / days)
        for metric in required_metrics
    }
    missing = sorted(metric for metric, ratio in coverage.items() if ratio == 0)
    weak = sorted(metric for metric, ratio in coverage.items() if 0 < ratio < 0.5)
    score = mean(coverage.values()) if coverage else 1.0
    return {
        "score": round(score, 3),
        "coverage": coverage,
        "missing_metrics": missing,
        "weak_metrics": weak,
        "message": "数据完整" if score >= 0.8 else "建议补充健康数据",
    }


def build_daily_summary(readings: Iterable[HealthReading], day: datetime) -> dict[str, object]:
    daily = [item for item in readings if item.measured_at.date() == day.date()]
    grouped = group_readings(daily)
    metrics = {
        metric: {
            "count": len(items),
            "average": round(mean(item.value for item in items), 2),
            "minimum": min(item.value for item in items),
            "maximum": max(item.value for item in items),
        }
        for metric, items in grouped.items()
    }
    signals = assess_health_risks(daily)
    return {
        "date": day.date().isoformat(),
        "metrics": metrics,
        "risk_count": len(signals),
        "highest_risk": signals[0].level if signals else "none",
        "recommendations": build_health_recommendations(signals),
    }
