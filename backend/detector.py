"""Deterministic, non-AI detector for publicly popular works."""

from dataclasses import asdict, dataclass


@dataclass(frozen=True)
class DetectionDecision:
    """Absolute public-metric classification for one observation."""

    status: str
    metric_name: str
    current_value: int | None
    hot_threshold: int
    very_hot_threshold: int
    enters_analysis: bool
    priority_analysis: bool
    reasons: tuple[str, ...]

    def evidence(self) -> dict:
        data = asdict(self)
        data["reasons"] = list(self.reasons)
        return data


def evaluate_public_metric(
    *,
    metric_name: str,
    current_value: int | None,
    hot_threshold: int,
    very_hot_threshold: int,
) -> DetectionDecision:
    """Classify a work using two explicit absolute thresholds.

    Thresholds intentionally have no defaults. Each platform must first prove
    which public metric it actually returns, then configure both values. The
    account's historic median is not an eligibility gate.
    """
    if hot_threshold < 0:
        raise ValueError("hot_threshold must be non-negative")
    if very_hot_threshold <= hot_threshold:
        raise ValueError("very_hot_threshold must be greater than hot_threshold")

    if current_value is None or isinstance(current_value, bool) or current_value < 0:
        return DetectionDecision(
            status="insufficient_data",
            metric_name=metric_name,
            current_value=None,
            hot_threshold=hot_threshold,
            very_hot_threshold=very_hot_threshold,
            enters_analysis=False,
            priority_analysis=False,
            reasons=("当前作品缺少已配置的公开流量指标",),
        )

    if current_value >= very_hot_threshold:
        status = "very_hot"
        enters_analysis = True
        priority_analysis = True
    elif current_value >= hot_threshold:
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
        hot_threshold=hot_threshold,
        very_hot_threshold=very_hot_threshold,
        enters_analysis=enters_analysis,
        priority_analysis=priority_analysis,
        reasons=(
            f"{metric_name}={current_value}",
            f"火门槛={hot_threshold}，特别火门槛={very_hot_threshold}",
        ),
    )
