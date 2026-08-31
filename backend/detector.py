"""Deterministic, non-AI detectors for account-relative popular works."""

from dataclasses import asdict, dataclass
from itertools import islice
from math import exp, log
from statistics import median
from typing import Iterable


BASELINE_WINDOW = 20
HOT_MULTIPLE = 3.0
VERY_HOT_MULTIPLE = 5.0


@dataclass(frozen=True)
class DetectionDecision:
    """Account-relative classification for one public metric observation."""

    status: str
    metric_name: str
    current_value: int | None
    finalized: bool
    baseline_value: float | None
    baseline_size: int
    baseline_missing_count: int
    relative_multiple: float | None
    hot_multiple: float
    very_hot_multiple: float
    enters_analysis: bool
    priority_analysis: bool
    reasons: tuple[str, ...]
    metric_values: dict[str, int] | None = None
    component_multiples: dict[str, float] | None = None

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
    finalized: bool,
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

    if not finalized:
        return DetectionDecision(
            status="pending_final_window",
            metric_name=metric_name,
            current_value=parsed_current_value,
            finalized=False,
            baseline_value=None,
            baseline_size=baseline_size,
            baseline_missing_count=baseline_missing_count,
            relative_multiple=None,
            hot_multiple=HOT_MULTIPLE,
            very_hot_multiple=VERY_HOT_MULTIPLE,
            enters_analysis=False,
            priority_analysis=False,
            reasons=("尚未到达发布后7天的最终观察窗口",),
        )

    if parsed_current_value is None:
        return DetectionDecision(
            status="insufficient_data",
            metric_name=metric_name,
            current_value=None,
            finalized=True,
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
            finalized=True,
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
            finalized=True,
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
            finalized=True,
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
        finalized=True,
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


_DEFAULT_PUBLIC_METRIC_WEIGHTS = {
    "view_count": 1.0,
    "like_count": 1.5,
    "comment_count": 1.0,
    "favorite_count": 1.5,
    "share_count": 1.0,
}


def _parse_metric_mapping(values: dict[str, int | None], metric_names: tuple[str, ...]) -> dict[str, int]:
    return {
        name: parsed
        for name in metric_names
        if (parsed := _parse_metric(values.get(name))) is not None
    }


def evaluate_public_metrics(
    *,
    metric_names: Iterable[str],
    current_values: dict[str, int | None],
    baseline_values: Iterable[dict[str, int | None]],
    finalized: bool,
) -> DetectionDecision:
    """Classify a work using whatever public metrics are actually available.

    The first 20 prior works are still required, but an individual missing
    metric no longer invalidates the whole baseline. Each metric contributes
    only when it has a positive median baseline and a current value. The final
    relative multiple is a weighted geometric mean of component multiples;
    likes and favorites receive a modestly higher weight because they are the
    most useful public interaction signals when views are unavailable.
    """
    names = tuple(dict.fromkeys(metric_names))
    raw_baseline = list(islice(baseline_values, BASELINE_WINDOW))
    current_metrics = _parse_metric_mapping(current_values, names)
    baseline_size = len(raw_baseline)
    parsed_baselines = [_parse_metric_mapping(row, names) for row in raw_baseline]
    baseline_missing_count = sum(1 for row in parsed_baselines if not row)

    if not finalized:
        return DetectionDecision(
            status="pending_final_window",
            metric_name="public_composite",
            current_value=None,
            finalized=False,
            baseline_value=None,
            baseline_size=baseline_size,
            baseline_missing_count=baseline_missing_count,
            relative_multiple=None,
            hot_multiple=HOT_MULTIPLE,
            very_hot_multiple=VERY_HOT_MULTIPLE,
            enters_analysis=False,
            priority_analysis=False,
            reasons=("尚未到达发布后7天的最终观察窗口",),
            metric_values=current_metrics,
            component_multiples={},
        )

    if baseline_size < BASELINE_WINDOW:
        return DetectionDecision(
            status="insufficient_data",
            metric_name="public_composite",
            current_value=None,
            finalized=True,
            baseline_value=None,
            baseline_size=baseline_size,
            baseline_missing_count=baseline_missing_count,
            relative_multiple=None,
            hot_multiple=HOT_MULTIPLE,
            very_hot_multiple=VERY_HOT_MULTIPLE,
            enters_analysis=False,
            priority_analysis=False,
            reasons=(f"只取到最近 {baseline_size} 条作品，需要完整的 20 条",),
            metric_values=current_metrics,
            component_multiples={},
        )

    if not current_metrics:
        return DetectionDecision(
            status="insufficient_data",
            metric_name="public_composite",
            current_value=None,
            finalized=True,
            baseline_value=None,
            baseline_size=baseline_size,
            baseline_missing_count=baseline_missing_count,
            relative_multiple=None,
            hot_multiple=HOT_MULTIPLE,
            very_hot_multiple=VERY_HOT_MULTIPLE,
            enters_analysis=False,
            priority_analysis=False,
            reasons=("当前作品没有可用的公开互动指标",),
            metric_values={},
            component_multiples={},
        )

    component_multiples: dict[str, float] = {}
    component_baselines: dict[str, float] = {}
    for name in names:
        current = current_metrics.get(name)
        samples = [row[name] for row in parsed_baselines if name in row]
        if current is None or len(samples) < 3:
            continue
        baseline = float(median(samples))
        if baseline > 0:
            component_baselines[name] = baseline
            component_multiples[name] = current / baseline

    if not component_multiples:
        return DetectionDecision(
            status="insufficient_data",
            metric_name="public_composite",
            current_value=max(current_metrics.values(), default=None),
            finalized=True,
            baseline_value=None,
            baseline_size=baseline_size,
            baseline_missing_count=baseline_missing_count,
            relative_multiple=None,
            hot_multiple=HOT_MULTIPLE,
            very_hot_multiple=VERY_HOT_MULTIPLE,
            enters_analysis=False,
            priority_analysis=False,
            reasons=("公开指标存在，但没有足够的历史样本形成可比较基线",),
            metric_values=current_metrics,
            component_multiples={},
        )

    total_weight = sum(_DEFAULT_PUBLIC_METRIC_WEIGHTS.get(name, 1.0) for name in component_multiples)
    relative_multiple = exp(
        sum(
            _DEFAULT_PUBLIC_METRIC_WEIGHTS.get(name, 1.0) * log(max(multiple, 0.000001))
            for name, multiple in component_multiples.items()
        )
        / total_weight
    )
    representative = max(component_multiples, key=component_multiples.get)
    if relative_multiple >= VERY_HOT_MULTIPLE:
        status, enters_analysis, priority_analysis = "very_hot", True, True
    elif relative_multiple >= HOT_MULTIPLE:
        status, enters_analysis, priority_analysis = "hot", True, False
    else:
        status, enters_analysis, priority_analysis = "observing", False, False

    return DetectionDecision(
        status=status,
        metric_name="public_composite",
        current_value=current_metrics[representative],
        finalized=True,
        baseline_value=component_baselines[representative],
        baseline_size=baseline_size,
        baseline_missing_count=baseline_missing_count,
        relative_multiple=relative_multiple,
        hot_multiple=HOT_MULTIPLE,
        very_hot_multiple=VERY_HOT_MULTIPLE,
        enters_analysis=enters_analysis,
        priority_analysis=priority_analysis,
        reasons=(
            f"综合 {len(component_multiples)} 个可用公开指标，代表指标={representative}",
            f"综合相对倍数={relative_multiple:.2f}，火={HOT_MULTIPLE:g}倍，特别火={VERY_HOT_MULTIPLE:g}倍",
        ),
        metric_values=current_metrics,
        component_multiples=component_multiples,
    )
