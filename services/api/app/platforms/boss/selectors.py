from dataclasses import dataclass


@dataclass(frozen=True)
class BossZhipinSelectors:
    """Selectors owned by the BOSS adapter, with semantic fallbacks."""

    job_cards: tuple[str, ...] = (
        ".job-card-wrap",
        ".job-card-wrapper",
        ".job-card-box",
        ".card-area",
        ".job-card",
        "[data-jobid]",
        "[data-job-id]",
    )
    job_title: tuple[str, ...] = (".job-name", ".job-title", "[data-job-title]")
    company_name: tuple[str, ...] = (
        ".boss-name",
        ".company-name",
        ".company-text",
        ".company-info",
    )
    location: tuple[str, ...] = (
        ".company-location",
        ".job-area",
        ".job-location",
        ".job-card-location",
    )
    salary: tuple[str, ...] = (".salary", ".job-salary", ".job-card-salary")
    job_link: tuple[str, ...] = ("a[href*='/job_detail/']", "a.job-card-left")
    detail_title: tuple[str, ...] = (
        ".job-detail-box .job-detail-info .job-name",
        ".job-banner .name",
        ".job-title",
        "h1",
    )
    detail_description: tuple[str, ...] = (
        ".job-detail-box .job-detail-body .desc",
        ".job-detail-box .job-detail-body",
        ".job-detail-container .job-detail-body",
        ".job-sec-text",
        ".job-detail",
        ".detail-content",
    )
    apply_button: tuple[str, ...] = (
        "button.btn-startchat",
        ".btn-startchat",
        ".btn-apply",
        "[data-testid='apply']",
    )


SELECTORS = BossZhipinSelectors()
