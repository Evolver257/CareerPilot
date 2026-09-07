from dataclasses import dataclass, field

from app.job_pipeline.adapters import get_source_adapter


@dataclass
class _ProviderJob:
    platform: str
    external_job_id: str
    source_url: str
    title: str
    location: str
    salary_text: str
    description: str
    raw_data: dict = field(default_factory=dict)


def test_boss_and_zhaopin_use_the_same_raw_contract() -> None:
    for source in ("boss", "zhaopin"):
        record = get_source_adapter(source).to_raw_record(
            _ProviderJob(
                platform=source,
                external_job_id="job-1",
                source_url=f"https://example.test/{source}/job-1",
                title="后端开发实习生",
                location="北京",
                salary_text="150-200元/天",
                description="【任职要求】\n本科，熟悉Python",
                raw_data={"company_name": "示例科技"},
            )
        )
        assert record.source == source
        assert record.source_job_id == "job-1"
        assert record.raw_payload["company_name"] == "示例科技"
        assert "Python" in record.description_html
