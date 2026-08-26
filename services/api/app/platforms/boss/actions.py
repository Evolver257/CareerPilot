from __future__ import annotations

from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from app.models.states import BrowserActionType
from app.platforms.boss.detectors import is_boss_url
from app.platforms.boss.selectors import SELECTORS
from app.schemas.browser import BrowserAction, BrowserTarget


def _task_url(source_url: str) -> str:
    if not is_boss_url(source_url):
        raise ValueError("BOSS adapter accepts only zhipin.com source URLs")
    parsed = urlsplit(source_url)
    query = parse_qsl(parsed.query, keep_blank_values=True)
    encoded_query = urlencode(query)
    if encoded_query:
        encoded_query += "&"
    encoded_query += "task={task_id}"
    return urlunsplit(
        (parsed.scheme, parsed.netloc, parsed.path, encoded_query, parsed.fragment)
    )


def build_application_actions(*, source_url: str) -> list[BrowserAction]:
    """Create user-visible actions; no credential or network action is generated."""

    return [
        BrowserAction(action=BrowserActionType.NAVIGATE, url=_task_url(source_url)),
        BrowserAction(action=BrowserActionType.CHECK_STATE),
        BrowserAction(
            action=BrowserActionType.CLICK,
            target=BrowserTarget(
                strategy="boss-semantic",
                name="立即沟通",
                selector=", ".join(SELECTORS.apply_button),
            ),
            metadata={
                "requires_user_approval": True,
                "external_side_effect": "application",
                "mode": "boss_immediate_communication",
            },
        ),
        BrowserAction(action=BrowserActionType.EXTRACT, metadata={"fields": ["result"]}),
    ]
