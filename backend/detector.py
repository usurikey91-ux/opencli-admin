"""Deterministic, non-AI detector for account-relative popular works."""

from dataclasses import asdict, dataclass
from itertools import islice
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
    baseline_missing_count: int
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


def _parse_metric(value: int | None) -> int | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        parsed = int(value)
    except (TypeError, ValueError, OverflowError):
        return None
    return parsed if parsed >= 0 else None


def _latest_window(values: Iterable[int | None]) -> tuple[list[int], int, int]:
    raw_window = list(islice(values, BASELINE_WINDOW))
    parsed_values: list[int] = []
    for value in raw_window:
        parsed = _parse_metric(value)
        if parsed is not None:
            parsed_values.append(parsed)
    return parsed_values, len(raw_window), len(raw_window) - len(parsed_values)


def evaluate_public_metric(
    *,
    metric_name: str,
    current_value: int | None,
    baseline_values: Iterable[int | None],
) -> DetectionDecision:
    """Compare a work with its account's latest 20 valid prior works.

    ``baseline_values`` must contain one value for every prior work, ordered by
    publication time newest first, and must not include the work being
    evaluated. Content type, advertising, or suspected paid traffic must not be
    filtered out. A missing metric inside the first 20 works makes the baseline
    incomplete; later works never substitute for it.
    """
    baseline_sample, baseline_size, baseline_missing_count = _latest_window(
        baseline_values
    )
    parsed_current_value = _parse_metric(current_value)

    if parsed_current_value is None:
        return DetectionDecision(
            status="insufficient_data",
            metric_name=metric_name,
            current_value=None,
            baseline_value=None,
            baseline_size=baseline_size,
            baseline_missing_count=baseline_missing_count,
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
            current_value=parsed_current_value,
            baseline_value=None,
            baseline_size=baseline_size,
            baseline_missing_count=baseline_missing_count,
            relative_multiple=None,
            hot_multiple=HOT_MULTIPLE,
            very_hot_multiple=VERY_HOT_MULTIPLE,
            enters_analysis=False,
            priority_analysis=False,
            reasons=(f"只取到最近 {baseline_size} 条作品，需要完整的 20 条",),
        )

    if baseline_missing_count:
        return DetectionDecision(
            status="insufficient_data",
            metric_name=metric_name,
            current_value=parsed_current_value,
            baseline_value=None,
            baseline_size=baseline_size,
            baseline_missing_count=baseline_missing_count,
            relative_multiple=None,
            hot_multiple=HOT_MULTIPLE,
            very_hot_multiple=VERY_HOT_MULTIPLE,
            enters_analysis=False,
            priority_analysis=False,
            reasons=(
                f"最近 20 条作品中有 {baseline_missing_count} 条缺少主公开指标，"
                "不使用更早作品补位",
            ),
        )

    baseline = float(median(baseline_sample))
    if baseline <= 0:
        return DetectionDecision(
            status="insufficient_data",
            metric_name=metric_name,
            current_value=parsed_current_value,
            baseline_value=baseline,
            baseline_size=baseline_size,
            baseline_missing_count=baseline_missing_count,
            relative_multiple=None,
            hot_multiple=HOT_MULTIPLE,
            very_hot_multiple=VERY_HOT_MULTIPLE,
            enters_analysis=False,
            priority_analysis=False,
            reasons=("账号日常中位数为零，无法计算相对倍数",),
        )

    relative_multiple = parsed_current_value / baseline
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
        current_value=parsed_current_value,
        baseline_value=baseline,
        baseline_size=baseline_size,
        baseline_missing_count=baseline_missing_count,
        relative_multiple=relative_multiple,
        hot_multiple=HOT_MULTIPLE,
        very_hot_multiple=VERY_HOT_MULTIPLE,
        enters_analysis=enters_analysis,
        priority_analysis=priority_analysis,
        reasons=(
            f"{metric_name}={parsed_current_value}，账号日常中位数={baseline:g}",
            f"相对倍数={relative_multiple:.2f}，火={HOT_MULTIPLE:g}倍，"
            f"特别火={VERY_HOT_MULTIPLE:g}倍",
        ),
    )
