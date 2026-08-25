"""Deterministic, non-AI detector for account-relative popular works."""

from dataclasses import asdict, dataclass
from statistics import median
from typing import Iterable


BASELINE_WINDOW = 20
HOT_MULTIPLE = 2.0
VERY_HOT_MULTIPLE = 5.0


@dataclass(frozen=True)
class DetectionDecision:
    """Account-relative classification for one public metric observation."""

    status: str
    metric_name: str
    current_value: int | None
    baseline_value: float | None
    baseline_size: int
    relative_multiple: float | None
    hot_multiple: float
    very_hot_multiple: float
    enters_analysis: bool
    priority_analysis: bool
    reasons: tuple[str, ...]

    def evidence(self) -> dict:
        data = asdict(self)
        data["reasons"] = list(self.reasons)
        return data


def _recent_valid_values(values: Iterable[int | None]) -> list[int]:
    result: list[int] = []
    for value in values:
        if value is None or isinstance(value, bool):
            continue
        try:
            parsed = int(value)
        except (TypeError, ValueError, OverflowError):
            continue
        if parsed < 0:
            continue
        result.append(parsed)
        if len(result) == BASELINE_WINDOW:
            break
    return result


def evaluate_public_metric(
    *,
    metric_name: str,
    current_value: int | None,
    baseline_values: Iterable[int | None],
) -> DetectionDecision:
    """Compare a work with its account's latest 20 valid prior works.

    ``baseline_values`` must be ordered newest first and must not include the
    work being evaluated. Upstream exclusions, such as manually ignored paid
    works, must be removed before calling this function.
    """
    baseline_sample = _recent_valid_values(baseline_values)
    baseline_size = len(baseline_sample)

    if current_value is None or isinstance(current_value, bool) or current_value < 0:
        return DetectionDecision(
            status="insufficient_data",
            metric_name=metric_name,
            current_value=None,
            baseline_value=None,
            baseline_size=baseline_size,
            relative_multiple=None,
            hot_multiple=HOT_MULTIPLE,
            very_hot_multiple=VERY_HOT_MULTIPLE,
            enters_analysis=False,
            priority_analysis=False,
            reasons=("当前作品缺少已选定的公开指标",),
        )

    if baseline_size < BASELINE_WINDOW:
        return DetectionDecision(
            status="insufficient_data",
            metric_name=metric_name,
            current_value=current_value,
            baseline_value=None,
            baseline_size=baseline_size,
            relative_multiple=None,
            hot_multiple=HOT_MULTIPLE,
            very_hot_multiple=VERY_HOT_MULTIPLE,
            enters_analysis=False,
            priority_analysis=False,
            reasons=(f"有效历史作品只有 {baseline_size} 条，需要最近 20 条",),
        )

    baseline = float(median(baseline_sample))
    if baseline <= 0:
        return DetectionDecision(
            status="insufficient_data",
            metric_name=metric_name,
            current_value=current_value,
            baseline_value=baseline,
            baseline_size=baseline_size,
            relative_multiple=None,
            hot_multiple=HOT_MULTIPLE,
            very_hot_multiple=VERY_HOT_MULTIPLE,
            enters_analysis=False,
            priority_analysis=False,
            reasons=("账号日常中位数为零，无法计算相对倍数",),
        )

    relative_multiple = current_value / baseline
    if relative_multiple >= VERY_HOT_MULTIPLE:
        status = "very_hot"
        enters_analysis = True
        priority_analysis = True
    elif relative_multiple >= HOT_MULTIPLE:
        status = "hot"
        enters_analysis = True
        priority_analysis = False
    else:
        status = "observing"
        enters_analysis = False
        priority_analysis = False

    return DetectionDecision(
        status=status,
        metric_name=metric_name,
        current_value=current_value,
        baseline_value=baseline,
        baseline_size=baseline_size,
        relative_multiple=relative_multiple,
        hot_multiple=HOT_MULTIPLE,
        very_hot_multiple=VERY_HOT_MULTIPLE,
        enters_analysis=enters_analysis,
        priority_analysis=priority_analysis,
        reasons=(
            f"{metric_name}={current_value}，账号日常中位数={baseline:g}",
            f"相对倍数={relative_multiple:.2f}，火={HOT_MULTIPLE:g}倍，"
            f"特别火={VERY_HOT_MULTIPLE:g}倍",
        ),
    )
