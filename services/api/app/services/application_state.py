from __future__ import annotations

from datetime import UTC, datetime

from app.models.entities import Application, Campaign
from app.models.states import ApplicationStatus, CampaignStatus


class InvalidStateTransitionError(ValueError):
    """Raised when a state machine action is not valid from the current state."""


class ApplicationStateMachine:
    transitions = {
        ApplicationStatus.DISCOVERED: {ApplicationStatus.ANALYZED},
        ApplicationStatus.ANALYZED: {ApplicationStatus.QUALIFIED, ApplicationStatus.FAILED},
        ApplicationStatus.QUALIFIED: {ApplicationStatus.WAITING_APPROVAL},
        ApplicationStatus.WAITING_APPROVAL: {ApplicationStatus.APPROVED},
        ApplicationStatus.APPROVED: {ApplicationStatus.QUEUED},
        ApplicationStatus.QUEUED: {ApplicationStatus.EXECUTING},
        ApplicationStatus.EXECUTING: {
            ApplicationStatus.SUBMITTED,
            ApplicationStatus.CAPTCHA_REQUIRED,
            ApplicationStatus.LOGIN_REQUIRED,
            ApplicationStatus.PLATFORM_LIMIT,
            ApplicationStatus.DOM_CHANGED,
            ApplicationStatus.FAILED,
        },
    }
    pausable = {ApplicationStatus.QUEUED, ApplicationStatus.EXECUTING}
    retryable = {
        ApplicationStatus.CAPTCHA_REQUIRED,
        ApplicationStatus.LOGIN_REQUIRED,
        ApplicationStatus.PLATFORM_LIMIT,
        ApplicationStatus.DOM_CHANGED,
        ApplicationStatus.FAILED,
    }
    terminal = {ApplicationStatus.SUBMITTED, ApplicationStatus.CANCELLED}

    def initialize(self, application: Application) -> None:
        application.status = ApplicationStatus.DISCOVERED.value
        application.application_metadata = {
            **(application.application_metadata or {}),
            "state_history": [self._event(None, ApplicationStatus.DISCOVERED, "create")],
        }

    def advance_to_waiting_approval(self, application: Application) -> None:
        self.transition(application, ApplicationStatus.ANALYZED, event="analyze")
        self.transition(application, ApplicationStatus.QUALIFIED, event="qualify")
        self.transition(
            application,
            ApplicationStatus.WAITING_APPROVAL,
            event="request_approval",
        )

    def transition(
        self,
        application: Application,
        target: ApplicationStatus,
        *,
        event: str,
    ) -> None:
        current = ApplicationStatus(application.status)
        if target not in self.transitions.get(current, set()):
            raise InvalidStateTransitionError(
                f"Application cannot transition from {current.value} to {target.value}"
            )
        metadata = dict(application.application_metadata or {})
        if target in self.retryable:
            metadata["resume_status"] = current.value
        self._record(application, metadata, current, target, event)
        if target == ApplicationStatus.SUBMITTED:
            application.applied_at = datetime.now(UTC)

    def pause(self, application: Application) -> None:
        current = ApplicationStatus(application.status)
        if current not in self.pausable:
            raise InvalidStateTransitionError(
                f"Application cannot pause from {current.value}"
            )
        metadata = dict(application.application_metadata or {})
        metadata["resume_status"] = current.value
        self._record(application, metadata, current, ApplicationStatus.PAUSED, "pause")

    def resume(self, application: Application) -> None:
        current = ApplicationStatus(application.status)
        if current != ApplicationStatus.PAUSED:
            raise InvalidStateTransitionError(
                f"Application cannot resume from {current.value}"
            )
        metadata = dict(application.application_metadata or {})
        target_value = metadata.get("resume_status")
        target = ApplicationStatus(target_value) if target_value else ApplicationStatus.QUEUED
        if target not in self.pausable:
            target = ApplicationStatus.QUEUED
        self._record(application, metadata, current, target, "resume")

    def retry(self, application: Application) -> None:
        current = ApplicationStatus(application.status)
        if current not in self.retryable:
            raise InvalidStateTransitionError(
                f"Application cannot retry from {current.value}"
            )
        metadata = dict(application.application_metadata or {})
        target_value = metadata.get("resume_status")
        target = ApplicationStatus(target_value) if target_value else ApplicationStatus.QUEUED
        if target not in {ApplicationStatus.QUEUED, ApplicationStatus.EXECUTING}:
            target = ApplicationStatus.QUEUED
        application.failure_reason = None
        self._record(application, metadata, current, target, "retry")

    def cancel(self, application: Application) -> None:
        current = ApplicationStatus(application.status)
        if current in self.terminal:
            raise InvalidStateTransitionError(
                f"Application cannot cancel from {current.value}"
            )
        metadata = dict(application.application_metadata or {})
        self._record(application, metadata, current, ApplicationStatus.CANCELLED, "cancel")

    def fail(self, application: Application, status: ApplicationStatus, reason: str) -> None:
        if status not in self.retryable:
            raise InvalidStateTransitionError(f"{status.value} is not a failure state")
        self.transition(application, status, event=status.value.casefold())
        application.failure_reason = reason

    @classmethod
    def _record(
        cls,
        application: Application,
        metadata: dict[str, object],
        current: ApplicationStatus,
        target: ApplicationStatus,
        event: str,
    ) -> None:
        history = list(metadata.get("state_history", []))
        history.append(cls._event(current, target, event))
        metadata["state_history"] = history
        application.application_metadata = metadata
        application.status = target.value

    @staticmethod
    def _event(
        current: ApplicationStatus | None,
        target: ApplicationStatus,
        event: str,
    ) -> dict[str, str | None]:
        return {
            "from": current.value if current else None,
            "to": target.value,
            "event": event,
            "at": datetime.now(UTC).isoformat(),
        }


class CampaignStateMachine:
    transitions = {
        CampaignStatus.DRAFT: {CampaignStatus.RANKING, CampaignStatus.CANCELLED},
        CampaignStatus.RANKING: {
            CampaignStatus.WAITING_APPROVAL,
            CampaignStatus.FAILED,
            CampaignStatus.CANCELLED,
        },
        CampaignStatus.WAITING_APPROVAL: {
            CampaignStatus.RUNNING,
            CampaignStatus.PAUSED,
            CampaignStatus.CANCELLED,
        },
        CampaignStatus.RUNNING: {
            CampaignStatus.PAUSED,
            CampaignStatus.COMPLETED,
            CampaignStatus.CANCELLED,
        },
        CampaignStatus.FAILED: {CampaignStatus.CANCELLED},
    }
    terminal = {CampaignStatus.COMPLETED, CampaignStatus.CANCELLED}

    def transition(self, campaign: Campaign, target: CampaignStatus) -> None:
        current = CampaignStatus(campaign.status)
        if target not in self.transitions.get(current, set()):
            raise InvalidStateTransitionError(
                f"Campaign cannot transition from {current.value} to {target.value}"
            )
        campaign.status = target.value
        if target == CampaignStatus.RANKING and campaign.started_at is None:
            campaign.started_at = datetime.now(UTC)
        if target in self.terminal:
            campaign.finished_at = datetime.now(UTC)

    def pause(self, campaign: Campaign) -> None:
        current = CampaignStatus(campaign.status)
        if current not in {CampaignStatus.WAITING_APPROVAL, CampaignStatus.RUNNING}:
            raise InvalidStateTransitionError(f"Campaign cannot pause from {current.value}")
        campaign.status_before_pause = current.value
        self.transition(campaign, CampaignStatus.PAUSED)

    def resume(self, campaign: Campaign) -> None:
        current = CampaignStatus(campaign.status)
        if current != CampaignStatus.PAUSED:
            raise InvalidStateTransitionError(f"Campaign cannot resume from {current.value}")
        target_value = campaign.status_before_pause
        target = CampaignStatus(target_value) if target_value else CampaignStatus.RUNNING
        if target not in {CampaignStatus.WAITING_APPROVAL, CampaignStatus.RUNNING}:
            target = CampaignStatus.RUNNING
        campaign.status = target.value
        campaign.status_before_pause = None

    def cancel(self, campaign: Campaign) -> None:
        current = CampaignStatus(campaign.status)
        if current == CampaignStatus.PAUSED:
            campaign.status = CampaignStatus.CANCELLED.value
            campaign.status_before_pause = None
            campaign.finished_at = datetime.now(UTC)
            return
        self.transition(campaign, CampaignStatus.CANCELLED)
