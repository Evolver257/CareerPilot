from datetime import UTC, datetime, timedelta

from app.job_pipeline import JobETLPipeline, RawJobRecord
from app.job_pipeline.cleaners import clean_job_text
from app.job_pipeline.dedup import is_probable_duplicate
from app.job_pipeline.evidence import validate_evidence
from app.job_pipeline.normalizers import (
    normalize_education,
    normalize_experience,
    normalize_salary,
    normalize_skills,
)
from app.job_pipeline.sections import parse_sections
from app.services.job_lifecycle import derive_lifecycle


def test_cleaner_removes_html_and_presentation_noise() -> None:
    result = clean_job_text(
        "<div>岗位职责</div><ul><li>负责 Python 服务</li></ul>"
        "<button>立即沟通</button><script>alert(1)</script>"
    )
    assert "负责 Python 服务" in result.text
    assert "立即沟通" not in result.text
    assert "alert" not in result.text


def test_salary_normalizer_preserves_unit_and_months() -> None:
    monthly = normalize_salary("15-25K·14薪")
    assert (monthly["minimum"], monthly["maximum"], monthly["months"]) == (15000, 25000, 14)
    assert normalize_salary("150-200元/天")["unit"] == "cny_day"
    assert normalize_salary("50-80元/小时")["unit"] == "cny_hour"
    assert normalize_salary("面议")["status"] == "negotiable"


def test_education_experience_and_skill_aliases() -> None:
    assert normalize_education("本科及以上") == "本科"
    assert normalize_experience("1-3年经验") == "1-3年"
    names = {item["name"] for item in normalize_skills("熟悉 Python、检索增强生成和 k8s")}
    assert {"Python", "RAG", "Kubernetes"}.issubset(names)


def test_location_normalizer_splits_city_and_district() -> None:
    from app.job_pipeline.normalizers import normalize_location

    assert normalize_location("武汉 洪山区")["city"] == "武汉"
    assert normalize_location("武汉 洪山区")["district"] == "洪山区"


def test_section_parser_identifies_jd_sections_and_items() -> None:
    parsed = parse_sections(
        "【岗位职责】\n1. 负责Agent服务\n2. 建设检索链路\n"
        "【任职要求】\n本科，熟悉Python\n【加分项】\n有RAG经验\n【福利待遇】\n弹性办公"
    )
    assert [item.text for item in parsed["responsibilities"]] == [
        "负责Agent服务",
        "建设检索链路",
    ]
    assert "本科，熟悉Python" in [item.text for item in parsed["requirements"]]
    assert parsed["preferred"][0].text == "有RAG经验"


def test_evidence_never_invents_source_text() -> None:
    valid = validate_evidence("Python", "任职要求：熟悉Python开发", section="requirements")
    invalid = validate_evidence("Kafka", "任职要求：熟悉Python开发", section="requirements")
    assert valid.valid and valid.confidence == 1.0
    assert not invalid.valid and invalid.evidence_text == ""


def test_pipeline_returns_canonical_job_and_quality_metadata() -> None:
    result = JobETLPipeline().process(
        RawJobRecord(
            source="boss",
            source_job_id="b-1",
            source_url="https://example.test/job/b-1",
            raw_title="AI Agent 实习生",
            raw_salary="150-200元/天",
            raw_location="北京·海淀区",
            description_html=(
                "【岗位职责】\n负责Python和RAG服务建设\n"
                "【任职要求】\n本科，熟悉Python，了解LangChain\n"
                "【福利待遇】\n弹性工作\n"
            ),
            raw_payload={"company_name": "示例科技", "experience": "经验不限", "job_type": "实习"},
        )
    )
    assert result.canonical["salary"]["minimum"] == 150
    assert result.canonical["role_family"] == "AI/LLM"
    assert result.canonical["employment_type"] == "实习"
    assert result.canonical["responsibilities"]
    assert result.canonical["quality"]["score"] > 0
    assert result.canonical["evidence"]


def test_duplicate_and_lifecycle_rules() -> None:
    left = {
        "source": "boss", "source_job_id": "1", "company": "示例科技",
        "title": "后端实习生", "location": "北京",
    }
    right = {
        "source": "zhaopin", "source_job_id": "2", "company": "示例科技",
        "title": "后端实习生", "location": "北京",
    }
    assert is_probable_duplicate(left, right)
    now = datetime.now(UTC)
    assert derive_lifecycle(now - timedelta(days=1), now=now) == "active"
    assert derive_lifecycle(now - timedelta(days=20), now=now) == "possibly_expired"
    assert derive_lifecycle(now - timedelta(days=40), now=now) == "expired"
