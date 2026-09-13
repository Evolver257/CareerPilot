from pydantic import ValidationError

from app.schemas.career_advisor_tools import (
    CAREER_ADVISOR_TOOL_INPUT_MODELS,
    CAREER_ADVISOR_TOOL_OUTPUT_MODELS,
    CollectJobsOnlineToolInput,
    CompareRoleProfilesToolInput,
)
from app.services.tool_governance import CAREER_ADVISOR_TOOL_MANIFESTS
from app.services.tool_protocol import definition_from_manifest


def test_every_advisor_tool_has_an_independent_input_and_output_contract() -> None:
    expected = set(CAREER_ADVISOR_TOOL_MANIFESTS)
    assert set(CAREER_ADVISOR_TOOL_INPUT_MODELS) == expected
    assert set(CAREER_ADVISOR_TOOL_OUTPUT_MODELS) == expected
    assert len(set(CAREER_ADVISOR_TOOL_INPUT_MODELS.values())) == len(expected)

    for name, manifest in CAREER_ADVISOR_TOOL_MANIFESTS.items():
        definition = definition_from_manifest(
            manifest,
            CAREER_ADVISOR_TOOL_INPUT_MODELS[name].model_json_schema(),
            CAREER_ADVISOR_TOOL_OUTPUT_MODELS[name].model_json_schema(),
        )
        assert definition.input_schema["type"] == "object"
        assert definition.output_schema["type"] == "object"
        assert definition.input_schema.get("additionalProperties") is False


def test_online_collection_contract_explains_required_fields_and_defaults() -> None:
    schema = CollectJobsOnlineToolInput.model_json_schema()
    assert schema["required"] == ["query"]
    assert schema["properties"]["platform"]["default"] == "auto"
    assert schema["properties"]["platform"]["enum"] == ["boss", "zhaopin", "auto"]
    assert schema["properties"]["max_jobs"]["default"] == 20
    assert schema["properties"]["quick_score_threshold"]["default"] == 60
    assert "BOSS" in schema["properties"]["platform"]["description"]

    parsed = CollectJobsOnlineToolInput.model_validate(
        {"query": "AI Agent 实习", "platform": "boss", "max_jobs": 30}
    )
    assert parsed.city == "北京"
    assert parsed.quick_score_threshold == 60


def test_role_comparison_contract_requires_exactly_two_roles() -> None:
    assert CompareRoleProfilesToolInput.model_validate(
        {"queries": ["AI Agent", "后端开发"]}
    ).queries == ["AI Agent", "后端开发"]

    try:
        CompareRoleProfilesToolInput.model_validate({"queries": ["AI Agent"]})
    except ValidationError:
        pass
    else:
        raise AssertionError("role comparison accepted fewer than two roles")
