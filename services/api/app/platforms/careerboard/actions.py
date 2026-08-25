from __future__ import annotations

from uuid import UUID

from app.models.states import BrowserActionType
from app.schemas.browser import BrowserAction, BrowserTarget


def build_application_actions(*, job_id: UUID, base_url: str) -> list[BrowserAction]:
    """Build semantic actions for a user-launched local browser session."""

    return [
        BrowserAction(
            action=BrowserActionType.NAVIGATE,
            url=f"{base_url}/mock-platform/jobs/{job_id}?task={{task_id}}",
        ),
        BrowserAction(action=BrowserActionType.CHECK_STATE),
        BrowserAction(
            action=BrowserActionType.CLICK,
            target=BrowserTarget(
                strategy="careerboard-semantic",
                name="立即投递",
                selector="[data-cp-action='apply']",
            ),
        ),
        BrowserAction(action=BrowserActionType.EXTRACT, metadata={"fields": ["result"]}),
    ]
