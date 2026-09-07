from datetime import UTC, datetime, timedelta

from app.models.entities import Job


def auto_delivery_cutoff(*, max_age_days: int, now: datetime | None = None) -> datetime:
    reference = now or datetime.now(UTC)
    if reference.tzinfo is None:
        reference = reference.replace(tzinfo=UTC)
    return reference - timedelta(days=max_age_days)


def is_fresh_for_auto_delivery(
    job: Job,
    *,
    max_age_days: int,
    now: datetime | None = None,
) -> bool:
    collected_at = job.last_collected_at
    if collected_at is None:
        return False
    if collected_at.tzinfo is None:
        collected_at = collected_at.replace(tzinfo=UTC)
    return collected_at >= auto_delivery_cutoff(max_age_days=max_age_days, now=now)


def stale_auto_delivery_reason(job: Job, *, max_age_days: int) -> str:
    collected_at = job.last_collected_at
    if collected_at.tzinfo is None:
        collected_at = collected_at.replace(tzinfo=UTC)
    collected_text = collected_at.astimezone(UTC).strftime("%Y-%m-%d %H:%M UTC")
    return (
        f"职位最近采集于 {collected_text}，已超过 {max_age_days} 天自动投递有效期；"
        "请重新检索该岗位后再加入自动投递。"
    )
