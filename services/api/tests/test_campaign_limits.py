from uuid import uuid4

import pytest
from pydantic import ValidationError

from app.schemas.campaigns import (
    CampaignApproveRequest,
    CampaignCreate,
    CampaignRejectRequest,
    CampaignUpdate,
    CuratedCampaignCreate,
)
from app.schemas.ranking import JobRankingRequest


@pytest.mark.parametrize("count", [1, 100, 200])
def test_plan_limits_agree_with_ranking_and_selection(count):
    assert CampaignCreate(name="Plan", max_jobs=count).max_jobs == count
    assert CampaignUpdate(max_jobs=count).max_jobs == count
    assert JobRankingRequest(final_top_k=count).final_top_k == count
    ids = [uuid4() for _ in range(count)]
    assert len(CuratedCampaignCreate(name="Plan", job_ids=ids).job_ids) == count
    assert len(CampaignApproveRequest(job_ids=ids).job_ids) == count
    assert len(CampaignRejectRequest(job_ids=ids).job_ids) == count


@pytest.mark.parametrize("count", [0, 201])
def test_plan_limits_reject_out_of_range(count):
    for model, payload in [
        (CampaignCreate, {"name": "Plan", "max_jobs": count}),
        (CampaignUpdate, {"max_jobs": count}),
        (JobRankingRequest, {"final_top_k": count}),
        (CuratedCampaignCreate, {"name": "Plan", "job_ids": [uuid4() for _ in range(count)]}),
        (CampaignApproveRequest, {"job_ids": [uuid4() for _ in range(count)]}),
        (CampaignRejectRequest, {"job_ids": [uuid4() for _ in range(count)]}),
    ]:
        with pytest.raises(ValidationError):
            model(**payload)
