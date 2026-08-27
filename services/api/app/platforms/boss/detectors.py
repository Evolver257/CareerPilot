from dataclasses import dataclass
from enum import StrEnum
from urllib.parse import urlsplit

from app.platforms.base import (
    CaptchaRequiredError,
    DomChangedError,
    LoginRequiredError,
    PlatformLimitError,
    RiskControlDetectedError,
    UnknownStateError,
)

ALLOWED_BOSS_HOSTS = frozenset({"zhipin.com", "www.zhipin.com", "m.zhipin.com"})


class BossPageState(StrEnum):
    READY = "READY"
    CAPTCHA = "CAPTCHA"
    LOGIN_REQUIRED = "LOGIN_REQUIRED"
    PLATFORM_LIMIT = "PLATFORM_LIMIT"
    RISK_CONTROL = "RISK_CONTROL"
    DOM_CHANGED = "DOM_CHANGED"
    UNKNOWN_STATE = "UNKNOWN_STATE"


@dataclass(frozen=True)
class BossPageSnapshot:
    html: str = ""
    text: str = ""
    url: str | None = None
    title: str | None = None


def is_boss_url(url: str | None) -> bool:
    if not url:
        return False
    hostname = (urlsplit(url).hostname or "").casefold()
    return hostname in ALLOWED_BOSS_HOSTS


class BossZhipinDetector:
    """Classify visible BOSS state before a state-changing browser action."""

    def detect(self, snapshot: BossPageSnapshot) -> BossPageState:
        content = "\n".join(
            part for part in (snapshot.html, snapshot.text, snapshot.title or "") if part
        ).casefold()
        if not is_boss_url(snapshot.url):
            raise UnknownStateError("BOSS page URL is not an approved zhipin.com host")
        if any(marker in content for marker in ("captcha", "验证码", "人机验证", "图形验证")):
            raise CaptchaRequiredError("BOSS CAPTCHA requires user action")
        if any(marker in content for marker in ("请先登录", "登录后", "登录/注册", "登录注册")):
            raise LoginRequiredError("BOSS login is required")
        if any(marker in content for marker in ("操作频繁", "访问频繁", "platform limit")):
            raise PlatformLimitError("BOSS platform limit requires user action")
        if any(
            marker in content
            for marker in (
                "安全验证",
                "风险验证",
                "请完成验证",
                "拖动滑块",
                "人机校验",
                "异常访问",
                "账号存在风险",
                "风险提示",
                "risk control verification",
                "security verification",
            )
        ):
            raise RiskControlDetectedError("BOSS risk control requires user action")
        if any(marker in content for marker in ("页面不存在", "dom changed")):
            raise DomChangedError("BOSS page structure changed; user review is required")

        ready_markers = ("职位搜索", "职位详情", "立即沟通", "立即投递", "薪资")
        if not any(marker in content for marker in ready_markers):
            raise UnknownStateError("BOSS page state is not recognized safely")
        return BossPageState.READY


detector = BossZhipinDetector()
