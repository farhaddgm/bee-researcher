"""Small, dependency-light price forecasting and evaluation engine."""

from __future__ import annotations

import math
from datetime import datetime, timedelta, timezone
from statistics import mean
from typing import Iterable, Mapping


MODEL_REVISION = "bee-cfo-forecast-1"
HORIZONS = (1, 7, 30)
MIN_OBSERVATIONS = 30
MIN_TREND_OBSERVATIONS = 90
MIN_STATISTICAL_OBSERVATIONS = 180
FLAT_THRESHOLD = 0.002
CHAMPION_CHALLENGER_REVISION = "bee-cfo-champion-challenger-1"
MIN_CHAMPION_CHALLENGER_SAMPLES = 20


def _finite(value: object) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) and number > 0 else None


def _normal_cdf(value: float) -> float:
    return 0.5 * (1.0 + math.erf(value / math.sqrt(2.0)))


def _clean_observations(observations: Iterable[Mapping[str, object]]) -> list[tuple[datetime, float]]:
    result: dict[datetime, float] = {}
    for item in observations:
        observed = item.get("observed_at")
        if isinstance(observed, str):
            try:
                observed = datetime.fromisoformat(observed.replace("Z", "+00:00"))
            except ValueError:
                continue
        if not isinstance(observed, datetime):
            continue
        observed = observed.replace(tzinfo=timezone.utc) if observed.tzinfo is None else observed.astimezone(timezone.utc)
        value = _finite(item.get("value"))
        if value is not None:
            result[observed] = value
    return sorted(result.items())


def _trend_and_volatility(values: list[float]) -> tuple[float, float]:
    returns = [math.log(values[index] / values[index - 1]) for index in range(1, len(values)) if values[index - 1] > 0]
    if not returns:
        return 0.0, 1e-6
    recent = returns[-min(20, len(returns)):]
    drift = sum(recent) / len(recent)
    alpha = 0.2
    ewma = 0.0
    for item in returns:
        ewma = alpha * ((item - drift) ** 2) + (1 - alpha) * ewma
    return drift, max(math.sqrt(ewma), 1e-6)


def _ema(values: list[float], *, span: int) -> float:
    """Return a deterministic EMA without introducing a heavy model runtime."""

    if not values:
        return 0.0
    alpha = 2.0 / (max(2, int(span)) + 1.0)
    result = values[0]
    for value in values[1:]:
        result = alpha * value + (1.0 - alpha) * result
    return result


def _mean_reversion_value(values: list[float], *, horizon: int) -> float:
    """A conservative local time-series component.

    It intentionally does not claim to be ARIMA/ETS.  It is enabled only
    after a longer local history exists and gently moves the last value
    toward a long EMA, which keeps it interpretable and backtestable.
    """

    last = values[-1]
    anchor = _ema(values[-min(120, len(values)):], span=min(60, len(values)))
    if last <= 0 or anchor <= 0:
        return last
    pull = min(0.35, 0.06 * max(1, int(horizon)))
    return last * math.exp(pull * math.log(anchor / last))


def _walk_forward_metrics(values: list[float]) -> dict[str, object]:
    """Compare the blend with last-value baseline on a time-ordered holdout."""
    start = max(MIN_OBSERVATIONS, len(values) - 20)
    baseline_errors: list[float] = []
    trend_errors: list[float] = []
    statistical_errors: list[float] = []
    ensemble_errors: list[float] = []
    baseline_percentage: list[float] = []
    ensemble_percentage: list[float] = []
    for index in range(start, len(values)):
        train = values[:index]
        drift, _ = _trend_and_volatility(train)
        baseline = train[-1]
        trend = baseline * math.exp(drift) if len(train) >= MIN_TREND_OBSERVATIONS else baseline
        statistical = _mean_reversion_value(train, horizon=1)
        statistical_weight = 0.15 if len(train) >= MIN_STATISTICAL_OBSERVATIONS else 0.0
        ensemble = (0.60 - statistical_weight / 2) * baseline + (0.40 - statistical_weight / 2) * trend + statistical_weight * statistical
        actual = values[index]
        baseline_errors.append(abs(actual - baseline))
        trend_errors.append(abs(actual - trend))
        if statistical_weight:
            statistical_errors.append(abs(actual - statistical))
        ensemble_errors.append(abs(actual - ensemble))
        baseline_percentage.append(abs(actual - baseline) / actual)
        ensemble_percentage.append(abs(actual - ensemble) / actual)
    if not ensemble_errors:
        return {"status": "no_call", "sample_size": 0}
    baseline_mae = mean(baseline_errors)
    ensemble_mae = mean(ensemble_errors)
    return {
        "status": "available",
        "sample_size": len(ensemble_errors),
        "baseline_mae": round(baseline_mae, 8),
        "trend_mae": round(mean(trend_errors), 8),
        "statistical_mae": round(mean(statistical_errors), 8) if statistical_errors else None,
        "ensemble_mae": round(ensemble_mae, 8),
        "baseline_mape": round(mean(baseline_percentage), 8),
        "ensemble_mape": round(mean(ensemble_percentage), 8),
        "improvement_vs_baseline": round((baseline_mae - ensemble_mae) / baseline_mae, 8) if baseline_mae else 0.0,
        "split": "time_ordered_last_20",
    }


def evaluate_champion_challenger(
    walk_forward: Mapping[str, object],
    *,
    minimum_samples: int = MIN_CHAMPION_CHALLENGER_SAMPLES,
) -> dict[str, object]:
    """Make a candidate eligible for review only after a time-ordered win."""
    try:
        samples = int(walk_forward.get("sample_size") or 0)
        champion_mae = float(walk_forward.get("baseline_mae"))
        challenger_mae = float(walk_forward.get("ensemble_mae"))
    except (TypeError, ValueError):
        return {
            "revision": CHAMPION_CHALLENGER_REVISION,
            "status": "insufficient_evidence",
            "eligible_for_owner_review": False,
            "public_target_permitted": False,
            "reason": "walk-forward metrics are incomplete",
        }
    eligible = (
        walk_forward.get("status") == "available"
        and samples >= minimum_samples
        and math.isfinite(champion_mae)
        and math.isfinite(challenger_mae)
        and challenger_mae <= champion_mae
    )
    return {
        "revision": CHAMPION_CHALLENGER_REVISION,
        "status": "eligible_for_owner_review" if eligible else "held",
        "eligible_for_owner_review": eligible,
        "public_target_permitted": False,
        "sample_size": samples,
        "minimum_samples": minimum_samples,
        "champion": "last_value_baseline",
        "challenger": "baseline_trend_mean_reversion_ensemble_v2",
        "champion_mae": champion_mae,
        "challenger_mae": challenger_mae,
        "improvement": round((champion_mae - challenger_mae) / champion_mae, 8) if champion_mae else None,
        "reason": None if eligible else "challenger has not beaten the champion on enough time-ordered observations",
    }


def build_price_forecasts(
    observations: Iterable[Mapping[str, object]],
    *,
    as_of: datetime,
    horizons: tuple[int, ...] = HORIZONS,
) -> dict[str, object]:
    """Return 1/7/30 day point and interval forecasts or an explicit no-call."""
    cleaned = _clean_observations(observations)
    data_cutoff = cleaned[-1][0] if cleaned else None
    base = {
        "model_revision": MODEL_REVISION,
        "method": "baseline_trend_mean_reversion_ensemble_v2",
        "data_cutoff": data_cutoff.isoformat() if data_cutoff else None,
        "sample_size": len(cleaned),
        "horizons": list(horizons),
        "limitations": [
            "این پیش‌بینی سناریوی آماری عمومی است و توصیه شخصی یا تضمین قیمت نیست.",
            "مدل عوامل کلان فقط پس از دریافت داده هم‌تراز و دارای provenance فعال می‌شود؛ در نبود آن no-call می‌ماند.",
        ],
    }
    if len(cleaned) < MIN_OBSERVATIONS:
        return {**base, "status": "no_call", "reason": f"حداقل {MIN_OBSERVATIONS} مشاهده معتبر لازم است", "forecasts": []}
    values = [value for _, value in cleaned]
    returns = [math.log(values[index] / values[index - 1]) for index in range(1, len(values)) if values[index - 1] > 0]
    if not returns:
        return {**base, "status": "no_call", "reason": "بازده لگاریتمی قابل محاسبه نیست", "forecasts": []}
    recent = returns[-min(20, len(returns)):]
    drift = sum(recent) / len(recent)
    overall_drift = sum(returns) / len(returns)
    alpha = 0.2
    ewma = 0.0
    for item in returns:
        ewma = alpha * ((item - drift) ** 2) + (1 - alpha) * ewma
    volatility = max(math.sqrt(ewma), 1e-6)
    last = values[-1]
    walk_forward = _walk_forward_metrics(values)
    champion_challenger = evaluate_champion_challenger(walk_forward)
    trend_weight = 0.40 if len(cleaned) >= MIN_TREND_OBSERVATIONS else 0.0
    if trend_weight and walk_forward.get("status") == "available" and float(walk_forward.get("ensemble_mae") or 0) > float(walk_forward.get("baseline_mae") or 0) * 1.05:
        trend_weight = 0.15
    statistical_weight = 0.15 if len(cleaned) >= MIN_STATISTICAL_OBSERVATIONS else 0.0
    baseline_weight = 1.0 - trend_weight - statistical_weight
    model_availability = {
        "baseline": {"status": "available", "minimum_observations": MIN_OBSERVATIONS},
        "trend_regime": {
            "status": "available" if len(cleaned) >= MIN_TREND_OBSERVATIONS else "limited",
            "minimum_observations": MIN_TREND_OBSERVATIONS,
        },
        "statistical_time_series": {
            "status": "available" if statistical_weight else "no_call",
            "method": "local_ema_mean_reversion",
            "minimum_observations": MIN_STATISTICAL_OBSERVATIONS,
            "reason": None if statistical_weight else "تاریخچه کافی برای جزء آماری بلندمدت وجود ندارد",
        },
        "macro_factor_model": {
            "status": "no_call",
            "reason": "داده عوامل کلان هم‌تراز و دارای provenance در این اجرا موجود نیست",
        },
        "scenario_simulation": {"status": "available", "method": "lognormal_uncertainty_band", "interval_confidence": 0.80},
    }
    forecasts: list[dict[str, object]] = []
    for horizon in horizons:
        if horizon <= 0:
            continue
        trend_value = last * math.exp(drift * horizon)
        statistical_value = _mean_reversion_value(values, horizon=horizon) if statistical_weight else None
        point = baseline_weight * last + trend_weight * trend_value + (statistical_weight * statistical_value if statistical_value is not None else 0.0)
        sigma = volatility * math.sqrt(horizon)
        z = 1.2815515655
        lower = point * math.exp(-z * sigma)
        upper = point * math.exp(z * sigma)
        mu = drift * horizon
        if sigma < 1e-6:
            probability_up = 1.0 if mu > FLAT_THRESHOLD else 0.0
            probability_down = 1.0 if mu < -FLAT_THRESHOLD else 0.0
        else:
            probability_up = 1 - _normal_cdf((FLAT_THRESHOLD - mu) / sigma)
            probability_down = _normal_cdf((-FLAT_THRESHOLD - mu) / sigma)
        probability_flat = max(0.0, 1.0 - probability_up - probability_down)
        total = probability_up + probability_down + probability_flat or 1.0
        quality = "available" if len(cleaned) >= 90 else "limited"
        forecasts.append({
            "horizon_days": horizon,
            "forecast_for": (as_of + timedelta(days=horizon)).isoformat(),
            "data_cutoff": data_cutoff.isoformat() if data_cutoff else None,
            "baseline_value": round(last, 8),
            "point_value": round(point, 8),
            "lower_value": round(lower, 8),
            "upper_value": round(upper, 8),
            "probability_up": round(probability_up / total, 6),
            "probability_down": round(probability_down / total, 6),
            "probability_flat": round(probability_flat / total, 6),
            "method": "baseline_trend_mean_reversion_ensemble_v2",
            "model_revision": MODEL_REVISION,
            "sample_size": len(cleaned),
            "quality_status": quality,
            "status": "open",
            "components": {
                "baseline_weight": baseline_weight,
                "trend_weight": trend_weight,
                "statistical_weight": statistical_weight,
                "baseline_value": round(last, 8),
                "trend_value": round(trend_value, 8),
                "statistical_value": round(statistical_value, 8) if statistical_value is not None else None,
                "recent_drift": round(drift, 8),
                "overall_drift": round(overall_drift, 8),
                "ewma_volatility": round(volatility, 8),
                "interval_confidence": 0.80,
            },
            "metrics": {
                "data_points": len(cleaned),
                "min_observations": MIN_OBSERVATIONS,
                "walk_forward": walk_forward,
                "benchmark": "last_value_baseline",
                "model_availability": model_availability,
                "champion_challenger": champion_challenger,
            },
        })
    return {
        **base,
        "status": "available" if forecasts else "no_call",
        "forecasts": forecasts,
        "model_availability": model_availability,
        "champion_challenger": champion_challenger,
    }


def evaluate_price_forecast(forecast: Mapping[str, object], actual_value: object) -> dict[str, object]:
    actual = _finite(actual_value)
    baseline = _finite(forecast.get("baseline_value"))
    point = _finite(forecast.get("point_value"))
    lower = _finite(forecast.get("lower_value"))
    upper = _finite(forecast.get("upper_value"))
    if actual is None or baseline is None or point is None:
        raise ValueError("actual_value and forecast numeric values must be positive")
    percentage_error = abs(actual - point) / actual if actual else None
    change = (actual / baseline) - 1 if baseline else 0.0
    actual_state = "up" if change > FLAT_THRESHOLD else "down" if change < -FLAT_THRESHOLD else "flat"
    probabilities = {
        "up": float(forecast.get("probability_up") or 0),
        "down": float(forecast.get("probability_down") or 0),
        "flat": float(forecast.get("probability_flat") or 0),
    }
    predicted_state = max(probabilities, key=probabilities.get)
    one_hot = {key: 1.0 if key == actual_state else 0.0 for key in probabilities}
    brier = sum((probabilities[key] - one_hot[key]) ** 2 for key in probabilities)
    return {
        "actual_value": actual,
        "absolute_error": abs(actual - point),
        "percentage_error": percentage_error,
        "direction_outcome": actual_state,
        "direction_hit": predicted_state == actual_state,
        "interval_covered": lower <= actual <= upper if lower is not None and upper is not None else None,
        "brier_score": min(1.0, max(0.0, brier)),
        "predicted_direction": predicted_state,
    }


def aggregate_calibration(records: Iterable[Mapping[str, object]]) -> dict[str, object]:
    rows = list(records)
    if not rows:
        return {"status": "no_call", "sample_size": 0}
    def avg(key: str) -> float | None:
        values = [float(row[key]) for row in rows if row.get(key) is not None]
        return mean(values) if values else None
    hits = [row for row in rows if row.get("direction_hit") is not None]
    covered = [row for row in rows if row.get("interval_covered") is not None]
    brier_values = [float(row["brier_score"]) for row in rows if row.get("brier_score") is not None]
    drift = None
    drift_status = "not_enough_history"
    if len(brier_values) >= 10:
        midpoint = len(brier_values) // 2
        drift = mean(brier_values[midpoint:]) - mean(brier_values[:midpoint])
        drift_status = "watch" if abs(drift) >= 0.10 else "stable"
    return {
        "status": "available",
        "sample_size": len(rows),
        "mae": avg("absolute_error"),
        "mape": avg("percentage_error"),
        "directional_accuracy": (sum(bool(row["direction_hit"]) for row in hits) / len(hits)) if hits else None,
        "interval_coverage": (sum(bool(row["interval_covered"]) for row in covered) / len(covered)) if covered else None,
        "mean_brier_score": avg("brier_score"),
        "calibration_drift": drift,
        "calibration_drift_status": drift_status,
        "limitations": ["کالیبراسیون با افزایش تعداد ارزیابی‌های واقعی معنادارتر می‌شود."],
    }
