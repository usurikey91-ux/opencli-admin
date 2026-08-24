"""Deterministic, non-AI detector for high-signal public works."""

from dataclasses import asdict, dataclass
from statistics import median
from typing import Iterable


@dataclass(frozen=True)
class DetectionDecision:
    status: str
    metric_name: str
    current_value: int | None
    baseline_value: float | None
    baseline_size: int
    relative_multiple: float | None
    absolute_threshold: int
    relative_threshold: float
    absolute_pass: bool
    relative_pass: bool
    confidence: str
    reasons: tuple[str, ...]

    def evidence(self) -> dict:
        data = asdict(self)
        data["reasons"] = list(self.reasons)
        return data


def evaluate_public_metric(
    *,
    metric_name: str,
    current_value: int | None,
    baseline_values: Iterable[int | None],
    absolute_threshold: int,
    relative_threshold: float,
    min_baseline_size: int = 5,
) -> DetectionDecision:
    """Apply the MVP dual gate: absolute floor plus account-relative median.

    Inputs are expected to come from comparable observation windows. The
    function deliberately does not infer causality or use model-generated data.
    """
    clean_baseline = [
        int(value)
        for value in baseline_values
        if value is not None and not isinstance(value, bool) and int(value) >= 0
    ]
    baseline_size = len(clean_baseline)
    absolute_pass = current_value is not None and current_value >= absolute_threshold

    if current_value is None or isinstance(current_value, bool) or current_value < 0:
        return DetectionDecision(
            status="insufficient_data",
            metric_name=metric_name,
            current_value=None,
            baseline_value=None,
            baseline_size=baseline_size,
            relative_multiple=None,
            absolute_threshold=absolute_threshold,
            relative_threshold=relative_threshold,
            absolute_pass=False,
            relative_pass=False,
            confidence="low",
            reasons=("当前作品缺少该公开指标",),
        )

    if baseline_size < min_baseline_size:
        return DetectionDecision(
            status="insufficient_data",
            metric_name=metric_name,
            current_value=current_value,
            baseline_value=None,
            baseline_size=baseline_size,
            relative_multiple=None,
            absolute_threshold=absolute_threshold,
            relative_threshold=relative_threshold,
            absolute_pass=absolute_pass,
            relative_pass=False,
            confidence="low",
            reasons=(f"有效基线只有 {baseline_size} 条，至少需要 {min_baseline_size} 条",),
        )

    baseline = float(median(clean_baseline))
    if baseline <= 0:
        return DetectionDecision(
            status="insufficient_data",
            metric_name=metric_name,
            current_value=current_value,
            baseline_value=baseline,
            baseline_size=baseline_size,
            relative_multiple=None,
            absolute_threshold=absolute_threshold,
            relative_threshold=relative_threshold,
            absolute_pass=absolute_pass,
            relative_pass=False,
            confidence="low",
            reasons=("账号基线中位数为零，无法计算可靠相对倍数",),
        )

    relative_multiple = current_value / baseline
    relative_pass = relative_multiple >= relative_threshold
    candidate = absolute_pass and relative_pass
    reasons = (
        f"{metric_name}={current_value}，绝对门槛={absolute_threshold}",
        f"账号基线中位数={baseline:g}，相对倍数={relative_multiple:.2f}",
    )
    return DetectionDecision(
        status="candidate" if candidate else "observing",
        metric_name=metric_name,
        current_value=current_value,
        baseline_value=baseline,
        baseline_size=baseline_size,
        relative_multiple=relative_multiple,
        absolute_threshold=absolute_threshold,
        relative_threshold=relative_threshold,
        absolute_pass=absolute_pass,
        relative_pass=relative_pass,
        confidence="medium" if baseline_size < 20 else "high",
        reasons=reasons,
    )
