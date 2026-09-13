import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";

const fixture = vi.hoisted(() => ({
  status: {
    dataset_version: "rag-v2.0.0",
    label_status: "awaiting_review",
    corpus_sha256: "hash",
    source_job_count: 1535,
    selected_job_count: 400,
    query_count: 200,
    candidate_pair_count: 1,
    annotation_quality: { stable_gold: false },
    progress: { annotator_a: { submitted: 0 }, annotator_b: { submitted: 0 } },
  },
  query: {
    query_id: "rag-v2-q001",
    query: "哪些岗位需要开发 AI Agent 或智能体",
    normalized_intent: "find_matching_jobs",
    query_type: "literal",
    target_role: ["AI Agent"],
    target_skills: ["Agent"],
    hard_constraints: {},
    soft_preferences: {},
    answerability: "answerable" as const,
    source: "human_written",
    generator_model: null,
    requires_human_review: true,
    template_group: "ai-agent",
    split: "train" as const,
    candidate_count: 1,
    annotated_count: 0,
    submitted_count: 0,
  },
  detail: {
    query: {
      query_id: "rag-v2-q001",
      query: "哪些岗位需要开发 AI Agent 或智能体",
      normalized_intent: "find_matching_jobs",
      query_type: "literal",
      target_role: ["AI Agent"],
      target_skills: ["Agent"],
      hard_constraints: {},
      soft_preferences: {},
      answerability: "answerable" as const,
      source: "human_written",
      generator_model: null,
      requires_human_review: true,
      template_group: "ai-agent",
      split: "train" as const,
    },
    items: [{
      job: {
        dataset_version: "rag-v2.0.0",
        job_id: "job-1",
        platform: "BOSS直聘",
        external_job_id: "ext-1",
        title: "AI Agent 后端工程师",
        company: "测试公司",
        description: "负责 AI Agent 工具调用和 Python 服务开发。",
        location: "武汉",
        city: "武汉",
        salary_min: 10,
        salary_max: 20,
        job_type: "社招",
        education_requirement: "本科",
        experience_requirement: "1-3年",
        education_level: "本科",
        experience_level: "1-3年",
        role_direction: "AI Agent",
        source_url: "https://example.test/job-1",
      },
      candidate_rank: 1,
      channels: ["hybrid"],
      annotation: null,
    }],
    labeler_view: { model_scores: false },
  },
}));

vi.mock("../../../lib/api", () => ({
  API_BASE_URL: "http://localhost:8010",
  getRagV2Status: vi.fn().mockResolvedValue(fixture.status),
  getRagV2Queries: vi.fn().mockResolvedValue([fixture.query]),
  getRagV2Query: vi.fn().mockResolvedValue(fixture.detail),
  saveRagV2Annotation: vi.fn().mockResolvedValue({}),
}));

afterEach(cleanup);

it("renders the three-column labeler view without model scores", async () => {
  const Page = (await import("./page")).default;
  render(<Page />);
  expect(await screen.findByText("哪些岗位需要开发 AI Agent 或智能体")).toBeInTheDocument();
  expect(await screen.findByText("AI Agent 后端工程师")).toBeInTheDocument();
  expect(screen.getByText("3 · 核心相关")).toBeInTheDocument();
  expect(screen.queryByText("模型分数")).not.toBeInTheDocument();
});
