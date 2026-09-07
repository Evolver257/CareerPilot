from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from urllib.parse import urlsplit

from app.platforms.base import ProviderErrorCode, RecruitmentProviderError

ZHAOPIN_HOSTS = frozenset({"zhaopin.com", "www.zhaopin.com", "sou.zhaopin.com", "m.zhaopin.com"})


class ZhaopinPageState(StrEnum):
    READY = "READY"
    LOGIN_REQUIRED = "LOGIN_REQUIRED"
    RATE_LIMITED = "RATE_LIMITED"
    VERIFICATION_REQUIRED = "VERIFICATION_REQUIRED"
    PAGE_CHANGED = "PAGE_CHANGED"
    UNKNOWN_STATE = "UNKNOWN_STATE"


@dataclass(frozen=True)
class ZhaopinPageSnapshot:
    url: str
    text: str = ""
    html: str = ""


def is_zhaopin_url(url: str | None) -> bool:
    return bool(url) and (urlsplit(url or "").hostname or "").casefold() in ZHAOPIN_HOSTS


class ZhaopinDetector:
    def detect(self, snapshot: ZhaopinPageSnapshot) -> ZhaopinPageState:
        if not is_zhaopin_url(snapshot.url):
            raise RecruitmentProviderError(
                "zhaopin",
                ProviderErrorCode.UNKNOWN,
                "智联招聘页面 URL 不是受支持的 zhaopin.com 地址",
                parser_stage="detect",
            )
        content = f"{snapshot.text}\n{snapshot.html}".casefold()
        if any(
            marker in content
            for marker in ("请先登录", "登录后查看", "登录/注册", "login required")
        ):
            raise RecruitmentProviderError(
                "zhaopin",
                ProviderErrorCode.AUTH_REQUIRED,
                "智联招聘当前需要用户登录",
                parser_stage="detect",
            )
        if any(marker in content for marker in ("安全验证", "人机验证", "验证码", "滑块验证")):
            raise RecruitmentProviderError(
                "zhaopin",
                ProviderErrorCode.VERIFICATION_REQUIRED,
                "智联招聘当前需要人工完成页面验证",
                parser_stage="detect",
            )
        if any(
            marker in content
            for marker in ("访问频繁", "操作频繁", "请求过于频繁", "too many requests")
        ):
            raise RecruitmentProviderError(
                "zhaopin",
                ProviderErrorCode.RATE_LIMITED,
                "智联招聘当前触发访问频率限制",
                parser_stage="detect",
            )
        if "页面不存在" in content or "page not found" in content:
            raise RecruitmentProviderError(
                "zhaopin",
                ProviderErrorCode.PAGE_CHANGED,
                "智联招聘页面不存在或结构发生变化",
                parser_stage="detect",
            )
        if not any(marker in content for marker in ("职位", "岗位", "薪资", "job", "position")):
            raise RecruitmentProviderError(
                "zhaopin",
                ProviderErrorCode.PAGE_CHANGED,
                "智联招聘页面尚未识别为职位搜索或详情页",
                parser_stage="detect",
            )
        return ZhaopinPageState.READY


detector = ZhaopinDetector()
