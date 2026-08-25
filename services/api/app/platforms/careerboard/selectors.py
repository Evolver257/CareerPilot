from dataclasses import dataclass


@dataclass(frozen=True)
class CareerBoardSelectors:
    """Selectors owned by the CareerBoard adapter only."""

    page_root: str = "[data-cp-page='job-detail']"
    job_title: str = "[data-cp-field='job-title']"
    location: str = "[data-cp-field='location']"
    apply_button: str = "[data-cp-action='apply']"
    captcha_marker: str = "[data-cp-state='captcha']"
    login_marker: str = "[data-cp-state='login-required']"
    risk_marker: str = "[data-cp-state='risk-control']"


SELECTORS = CareerBoardSelectors()
