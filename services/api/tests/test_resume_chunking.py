from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.config import get_settings
from app.llm.provider import MockLLMProvider
from app.llm.tokenization import CallableTokenCounter
from app.models.base import Base
from app.models.entities import Resume, ResumeChunk, User
from app.repositories.matching import MatchingRepository
from app.schemas.resumes import ResumeExperience, ResumeProfile, ResumeProject
from app.services.resume_chunking import RESUME_CHUNKING_VERSION, ResumeSemanticChunker
from app.services.resume_extraction import HeuristicResumeExtractor
from app.services.resume_rag import ResumeRAG


def test_resume_chunker_keeps_projects_and_experiences_as_separate_evidence() -> None:
    profile = ResumeProfile(
        experience=[
            ResumeExperience(company="甲公司", role="后端实习生", bullets=["开发订单服务"]),
            ResumeExperience(company="乙公司", role="算法实习生", bullets=["训练检索模型"]),
        ],
        projects=[
            ResumeProject(
                name="CareerPilot", description="构建求职 Agent", technologies=["Python"]
            ),
            ResumeProject(
                name="MiniMind", description="训练小型语言模型", technologies=["PyTorch"]
            ),
        ],
    )

    drafts = ResumeSemanticChunker().chunk("", profile)
    projects = [draft for draft in drafts if draft.chunk_type == "project"]
    experiences = [draft for draft in drafts if draft.chunk_type == "experience"]

    assert len(projects) == 2
    assert len(experiences) == 2
    assert "CareerPilot" in projects[0].content and "MiniMind" not in projects[0].content
    assert "MiniMind" in projects[1].content and "CareerPilot" not in projects[1].content
    assert {draft.metadata["item_index"] for draft in projects} == {0, 1}
    assert all(draft.metadata["chunking_version"] == RESUME_CHUNKING_VERSION for draft in drafts)
    assert all(len(str(draft.metadata["content_hash"])) == 64 for draft in drafts)


def test_resume_chunker_repeats_item_identity_and_respects_size_for_long_projects() -> None:
    profile = ResumeProfile(
        projects=[
            ResumeProject(
                name="大型知识库项目",
                description="。".join(f"完成第{index}项检索优化" for index in range(120)),
                technologies=["Python", "PostgreSQL", "RAG"],
            )
        ]
    )

    drafts = ResumeSemanticChunker(chunk_size=600, overlap=80).chunk("", profile)
    projects = [draft for draft in drafts if draft.chunk_type == "project"]

    assert len(projects) > 1
    assert all(len(draft.content) <= 600 for draft in projects)
    assert all(draft.content.startswith("name: 大型知识库项目") for draft in projects)
    assert [draft.metadata["part_index"] for draft in projects] == list(range(len(projects)))


def test_resume_chunker_respects_exact_provider_token_limit() -> None:
    counter = CallableTokenCounter(
        callback=len,
        signature="test:character-tokenizer-v1",
        exact=True,
    )
    profile = ResumeProfile(
        projects=[
            ResumeProject(
                name="长项目",
                description="负责需求分析、系统设计、编码、测试和部署。" * 30,
                technologies=["Python", "RAG"],
            )
        ]
    )

    drafts = ResumeSemanticChunker(
        chunk_size=300,
        overlap=40,
        token_limit=120,
        token_overlap=20,
        token_counter=counter,
    ).chunk("", profile)

    assert len(drafts) > 1
    assert all(int(draft.metadata["token_count"]) <= 120 for draft in drafts)
    assert all(
        draft.metadata["tokenizer_signature"] == "test:character-tokenizer-v1"
        for draft in drafts
    )
    assert all(draft.metadata["token_count_exact"] is True for draft in drafts)


async def test_resume_rag_rebuilds_chunks_created_by_an_older_chunker() -> None:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)

    async with session_factory() as session:
        user = User(email="chunk-test@example.com", name="Chunk Test")
        resume = Resume(
            user=user,
            name="旧版简历",
            raw_text="项目经历\nCareerPilot - 构建求职 Agent",
            structured_profile=ResumeProfile(
                projects=[
                    ResumeProject(
                        name="CareerPilot",
                        description="构建求职 Agent",
                        technologies=["Python"],
                    )
                ]
            ).model_dump(),
        )
        stale = ResumeChunk(
            resume=resume,
            chunk_type="project",
            content="旧版混合项目块",
            chunk_metadata={"source": "structured_profile"},
            embedding=await MockLLMProvider().embed("旧版混合项目块"),
        )
        session.add_all([resume, stale])
        await session.commit()

        rag = ResumeRAG(MatchingRepository(session), MockLLMProvider(), get_settings())
        await rag._ensure_resume_embeddings(resume)

        chunks = list(
            (
                await session.scalars(select(ResumeChunk).where(ResumeChunk.resume_id == resume.id))
            ).all()
        )
        assert stale.id not in {chunk.id for chunk in chunks}
        assert len(chunks) == 1
        assert chunks[0].content.startswith("name: CareerPilot")
        assert chunks[0].chunk_metadata["chunking_version"] == RESUME_CHUNKING_VERSION

    await engine.dispose()


def test_resume_extractor_groups_experience_heading_and_bullets() -> None:
    profile = HeuristicResumeExtractor().extract(
        """工作经验
2025.01 - 2025.06 甲公司 | AI 实习生
- 构建 RAG 检索服务
- 优化向量召回率
2025.07 - 2025.09 乙公司 | 后端实习生
- 开发 FastAPI 接口
"""
    )

    assert len(profile.experience) == 2
    assert profile.experience[0].company == "甲公司"
    assert profile.experience[0].role == "AI 实习生"
    assert profile.experience[0].bullets == ["构建 RAG 检索服务", "优化向量召回率"]
