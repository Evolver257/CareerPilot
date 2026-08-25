from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from app.platforms.base import (
    CaptchaRequiredError,
    LoginRequiredError,
    RiskControlDetectedError,
    UnknownStateError,
)
from app.platforms.careerboard.selectors import SELECTORS


class CareerBoardPageState(StrEnum):
    READY = "READY"
    CAPTCHA = "CAPTCHA"
    LOGIN_REQUIRED = "LOGIN_REQUIRED"
    RISK_CONTROL = "RISK_CONTROL"
    UNKNOWN_STATE = "UNKNOWN_STATE"


@dataclass(frozen=True)
class PageSnapshot:
    html: str = ""
    text: str = ""
    url: str | None = None
    title: str | None = None


class CareerBoardDetector:
    """Classify a page before any state-changing action is attempted."""

    def detect(self, snapshot: PageSnapshot) -> CareerBoardPageState:
        content = "\n".join(
            part for part in (snapshot.html, snapshot.text, snapshot.title or "") if part
        ).casefold()
        if self._has_state(snapshot, "captcha") or any(
            marker in content for marker in ("captcha", "人机验证")
        ):
            raise CaptchaRequiredError("CareerBoard CAPTCHA requires user action")
        if self._has_state(snapshot, "login-required") or any(
            marker in content for marker in ("login required", "sign in", "请先登录", "登录后")
        ):
            raise LoginRequiredError("CareerBoard login is required")
        if self._has_state(snapshot, "risk-control") or any(
            marker in content for marker in ("risk control", "安全验证", "操作频繁", "风控")
        ):
            raise RiskControlDetectedError("CareerBoard risk control requires user action")

        has_expected_dom = all(
            self._has_selector_attribute(snapshot.html, selector)
            for selector in (SELECTORS.page_root, SELECTORS.job_title)
        )
        has_ready_text = any(marker in snapshot.text for marker in ("立即投递", "已投递"))
        if not has_expected_dom and not has_ready_text:
            raise UnknownStateError("CareerBoard page state is not recognized safely")
        return CareerBoardPageState.READY

    @staticmethod
    def _has_state(snapshot: PageSnapshot, state: str) -> bool:
        return (
            f'data-cp-state="{state}"' in snapshot.html
            or f"data-cp-state='{state}'" in snapshot.html
        )

    @staticmethod
    def _has_selector_attribute(html: str, selector: str) -> bool:
        if not selector.startswith("[") or "=" not in selector:
            return False
        attribute, value = selector[1:-1].split("=", 1)
        value = value.strip("\"'")
        return f'{attribute}="{value}"' in html or f"{attribute}='{value}'" in html


detector = CareerBoardDetector()
