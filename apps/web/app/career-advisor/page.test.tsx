import { act, cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import Page from "./page";
import {
  confirmCareerAdvisorApplication,
  prepareCareerAdvisorApplication,
  streamCareerAdvisorMessage,
  type CareerAdvisorSession,
  type CareerAdvisorUiAction,
} from "../../lib/api";

const data = vi.hoisted(() => {
  const answer = (id: string, content: string, sample: number) => ({ id, session_id: "session", role: "assistant" as const, status: "COMPLETED" as const, content, citations: [], answer_metadata: { sample_count: sample, fact_source: "database", advice_source: "llm", data_sufficient: true }, tool_trace: [], token_usage: {}, created_at: "2026-09-04T00:00:00Z", updated_at: "2026-09-04T00:00:00Z", intent: null, model_provider: null, model_name: null, latency_ms: 0, error_message: null });
  return { session: { id: "session", title: "Agent 学习路线", resume_id: null, context_filters: { cities: [], job_types: [] }, updated_at: "2026-09-04T00:00:00Z", messages: [answer("first", "先学习 Python", 11), answer("second", "接下来学习 RAG", 22)] } };
});
vi.mock("../../lib/api", () => ({
  getCareerAdvisorSessions: vi.fn().mockResolvedValue({ items: [data.session], total: 1 }),
  getCareerAdvisorSession: vi.fn().mockResolvedValue(data.session),
  getResumes: vi.fn().mockResolvedValue({ items: [] }),
  getKnowledgeHealth: vi.fn().mockResolvedValue({ ready: true, indexed_jobs: 20, jobs_total: 20, chunk_count: 100, latest_run: { id: "index", status: "SUCCEEDED" } }),
  markAgentMemoryOutdated: vi.fn(),
  streamCareerAdvisorMessage: vi.fn(),
  streamCareerAdvisorRecovery: vi.fn(),
  updateAgentMemory: vi.fn(),
  prepareCareerAdvisorApplication: vi.fn(),
  confirmCareerAdvisorApplication: vi.fn(),
  getCareerAdvisorApplicationProgress: vi.fn(),
  cancelCareerAdvisorApplication: vi.fn(),
}));
vi.mock("../../components/boss-plugin-workflow", () => ({
  BossPluginWorkflow: ({ initialRequirements, initialCity, initialMaxJobs, initialQuickScoreThreshold }: Record<string, unknown>) => <div aria-label="BOSS 联网采集">{String(initialRequirements)} · {String(initialCity)} · {String(initialMaxJobs)} · {String(initialQuickScoreThreshold)}</div>,
}));
vi.mock("../../components/zhaopin-plugin-workflow", () => ({
  ZhaopinPluginWorkflow: ({ initialKeyword }: Record<string, unknown>) => <div aria-label="智联联网采集">{String(initialKeyword)}</div>,
}));
beforeEach(() => {
  vi.clearAllMocks(); localStorage.clear();
  HTMLDialogElement.prototype.showModal = function () { this.setAttribute("open", ""); };
  HTMLDialogElement.prototype.close = function () { this.removeAttribute("open"); };
});
afterEach(cleanup);

it("opens evidence for the clicked answer rather than the latest answer", async () => {
  render(<Page />);
  const buttons = await screen.findAllByRole("button", { name: "参考岗位 · 0 条依据" });
  expect(screen.getByRole("button", { name: "进入专注聊天" })).toHaveAttribute("aria-pressed", "true");
  fireEvent.click(buttons[0]);
  const panel = screen.getByRole("dialog", { name: "这条回答的依据" });
  expect(within(panel).getByText("11")).toBeInTheDocument();
  expect(within(panel).getByText("单次知识检索")).toBeInTheDocument();
  expect(within(panel).queryByText("22")).not.toBeInTheDocument();
  expect(screen.queryByRole("region", { name: "岗位候选" })).not.toBeInTheDocument();
  fireEvent.click(within(panel).getByRole("button", { name: "关闭这条回答的依据" }));
  expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  expect(screen.queryByText("知识库正在增量更新")).not.toBeInTheDocument();
  expect(screen.queryByRole("button", { name: /全量回填|增量更新/ })).not.toBeInTheDocument();
});

it("shows the online collection workflow only when the agent emitted that tool action", async () => {
  const collectionAction: CareerAdvisorUiAction = {
    type: "job_collection_request",
    action_id: "collect-1",
    result_source: "automated_collection",
    platform: "boss",
    query: "RAG 实习",
    city: "上海",
    max_jobs: 40,
    quick_score_threshold: 65,
    auto_start: true,
  };
  const actionMessage = {
    ...data.session.messages[1],
    answer_metadata: { ...data.session.messages[1].answer_metadata, ui_action: collectionAction },
    ui_action: collectionAction,
  };
  const actionSession = { ...data.session, messages: [actionMessage] } as unknown as CareerAdvisorSession;
  const api = await import("../../lib/api");
  vi.mocked(api.getCareerAdvisorSessions).mockResolvedValueOnce({ items: [actionSession], total: 1, limit: 30, offset: 0, has_more: false });
  vi.mocked(api.getCareerAdvisorSession).mockResolvedValueOnce(actionSession);

  render(<Page />);
  expect(await screen.findByLabelText("BOSS 联网采集")).toHaveTextContent("RAG 实习 · 上海 · 40 · 65");
  expect(screen.queryByRole("region", { name: "岗位候选" })).not.toBeInTheDocument();
});

it("keeps job search, confirmation, and progress inside the chat", async () => {
  const job = {
    id: "job-1",
    title: "AI Agent 实习生",
    company: "CareerPilot",
    location: "北京",
    platform: "boss",
    salary_text: "200-300 元/天",
    match_score: 86,
    match_reason: "Python 与 RAG 项目经验匹配",
    default_selected: true,
    warnings: [],
    source_url: "https://example.com/job-1",
  };
  const searchAction: CareerAdvisorUiAction = {
    type: "job_search_results",
    result_source: "knowledge_base",
    action_id: "job-search-1",
    title: "为你找到 1 个相关岗位",
    summary: "北京 · 实习 · 近 3 天优先",
    jobs: [job],
    default_selected_job_ids: [job.id],
    low_match_job_ids: [],
    expired_job_ids: [],
  };
  const confirmationAction: CareerAdvisorUiAction = {
    type: "application_confirmation",
    action_id: "application-confirm-1",
    campaign_id: "campaign-1",
    plan_name: "职业顾问投递计划",
    job_ids: [job.id],
    jobs: [job],
    confirmation_token: "a".repeat(32),
    status: "awaiting_user",
  };
  const progressAction: CareerAdvisorUiAction = {
    type: "application_progress",
    action_id: "application-progress-1",
    campaign_id: "campaign-1",
    items: [{ task_id: "task-1", job_id: job.id, job_title: job.title, task_status: "CONNECTING", application_status: "EXECUTING" }],
    total_count: 1,
    submitted_count: 0,
    manual_count: 0,
    waiting_count: 0,
    status: "running",
  };
  const actionMessage = {
    ...data.session.messages[1],
    answer_metadata: { ...data.session.messages[1].answer_metadata, ui_action: searchAction },
    ui_action: searchAction,
  };
  const actionSession = { ...data.session, messages: [actionMessage] } as unknown as CareerAdvisorSession;
  const api = await import("../../lib/api");
  vi.mocked(api.getCareerAdvisorSessions).mockResolvedValueOnce({ items: [actionSession], total: 1, limit: 30, offset: 0, has_more: false });
  vi.mocked(api.getCareerAdvisorSession).mockResolvedValueOnce(actionSession);
  vi.mocked(prepareCareerAdvisorApplication).mockResolvedValue({ message_id: actionMessage.id, ui_action: confirmationAction });
  vi.mocked(confirmCareerAdvisorApplication).mockResolvedValue({ message_id: actionMessage.id, ui_action: progressAction });

  render(<Page />);
  await screen.findByRole("region", { name: "岗位候选" });
  fireEvent.click(screen.getByRole("button", { name: "准备投递 1 个岗位" }));
  await waitFor(() => expect(prepareCareerAdvisorApplication).toHaveBeenCalledTimes(1));
  await screen.findByRole("region", { name: "投递确认" });
  fireEvent.click(screen.getByRole("button", { name: "确认并开始投递 1 个岗位" }));
  await screen.findByRole("region", { name: "投递进度" });
  expect(confirmCareerAdvisorApplication).toHaveBeenCalledWith("session", expect.objectContaining({ campaign_id: "campaign-1" }));
});
it("keeps the composer editable during streaming and preserves next-question drafts", async () => {
  let finish!: () => void;
  vi.mocked(streamCareerAdvisorMessage).mockImplementation(() => new Promise<Awaited<ReturnType<typeof streamCareerAdvisorMessage>>>((resolve) => { finish = () => resolve(data.session.messages[1] as Awaited<ReturnType<typeof streamCareerAdvisorMessage>>); }));
  const view = render(<Page />);
  await screen.findByText("先学习 Python");
  const input = screen.getByRole("textbox", { name: "向职业顾问提问" });
  fireEvent.change(input, { target: { value: "学习哪些技术？" } });
  fireEvent.keyDown(input, { key: "Enter", isComposing: true });
  expect(streamCareerAdvisorMessage).not.toHaveBeenCalled();
  fireEvent.keyDown(input, { key: "Enter", shiftKey: true });
  expect(streamCareerAdvisorMessage).not.toHaveBeenCalled();
  fireEvent.keyDown(input, { key: "Enter" });
  await waitFor(() => expect(streamCareerAdvisorMessage).toHaveBeenCalledTimes(1));
  expect(input).not.toBeDisabled();
  fireEvent.change(input, { target: { value: "下一条问题草稿" } });
  fireEvent.keyDown(input, { key: "Enter" });
  expect(streamCareerAdvisorMessage).toHaveBeenCalledTimes(1);
  await act(async () => finish());
  expect(input).toHaveValue("下一条问题草稿");
  view.unmount(); render(<Page />);
  await waitFor(() => expect(screen.getByRole("textbox", { name: "向职业顾问提问" })).toHaveValue("下一条问题草稿"));
});

it("renders actual Agent stages and tool summaries while the server stream is running", async () => {
  let finish!: () => void;
  vi.mocked(streamCareerAdvisorMessage).mockImplementation((_sessionId, _payload, onEvent) => {
    onEvent("message_started", { message_id: "run-1", run_id: "run-1", event_id: "run-start" });
    onEvent("stage_changed", { message_id: "run-1", stage: "searching", label: "正在检索岗位知识库", event_id: "stage-search" });
    onEvent("tool_finished", { message_id: "run-1", tool: "search_job_knowledge", event_id: "tool-1", output: { sample_count: 12, citation_count: 6 } });
    return new Promise((resolve) => { finish = () => resolve(data.session.messages[1] as Awaited<ReturnType<typeof streamCareerAdvisorMessage>>); });
  });
  render(<Page />);
  const input = await screen.findByRole("textbox", { name: "向职业顾问提问" });
  fireEvent.change(input, { target: { value: "分析 AI Agent 岗位" } });
  fireEvent.keyDown(input, { key: "Enter" });
  await waitFor(() => expect(screen.getAllByText("正在检索岗位知识库").length).toBeGreaterThanOrEqual(1));
  expect(screen.getAllByText("检索岗位知识库").length).toBeGreaterThanOrEqual(1);
  expect(screen.getAllByRole("button", { name: "停止生成" })).toHaveLength(1);
  await act(async () => finish());
});

it("removes the preparing placeholder as soon as answer generation fails", async () => {
  vi.mocked(streamCareerAdvisorMessage).mockImplementation((_sessionId, _payload, onEvent) => {
    onEvent("message_started", { message_id: "failed-run", run_id: "failed-run", event_id: "failed-start" });
    onEvent("message_failed", { message_id: "failed-run", error: "职业顾问回答生成失败", event_id: "failed-end" });
    return new Promise(() => undefined);
  });

  render(<Page />);
  const input = await screen.findByRole("textbox", { name: "向职业顾问提问" });
  fireEvent.change(input, { target: { value: "分析适合我的岗位" } });
  fireEvent.keyDown(input, { key: "Enter" });

  await waitFor(() => expect(screen.getAllByText("职业顾问回答生成失败").length).toBeGreaterThan(0));
  expect(screen.queryByText("回答正在准备中…")).not.toBeInTheDocument();
  expect(screen.queryByRole("button", { name: "停止生成" })).not.toBeInTheDocument();
});

it("provides searchable history without blocking the chat layout", async () => {
  render(<Page />);
  await screen.findByText("先学习 Python");
  fireEvent.click(screen.getByRole("button", { name: "咨询记录" }));
  const panel = screen.getByRole("dialog", { name: "咨询记录" });
  fireEvent.change(within(panel).getByRole("textbox", { name: "搜索已加载咨询" }), { target: { value: "其他主题" } });
  expect(within(panel).getByText(/未找到匹配的咨询/)).toBeInTheDocument();
});

it("lets the user correct or retire memory shown in answer evidence", async () => {
  const memoryAnswer = {
    ...data.session.messages[0],
    answer_metadata: {
      ...data.session.messages[0].answer_metadata,
      memory: {
        needed: true,
        used_count: 1,
        items: [{ id: "memory-1", memory_key: "skill.python", content: "我会 Python", user_confirmed: false }],
      },
    },
  };
  const memorySession = { ...data.session, messages: [memoryAnswer] } as unknown as CareerAdvisorSession;
  const api = await import("../../lib/api");
  vi.mocked(api.getCareerAdvisorSessions).mockResolvedValueOnce({ items: [memorySession], total: 1, limit: 30, offset: 0, has_more: false });
  vi.mocked(api.getCareerAdvisorSession).mockResolvedValueOnce(memorySession);
  vi.mocked(api.updateAgentMemory).mockResolvedValue({} as never);
  vi.mocked(api.markAgentMemoryOutdated).mockResolvedValue({} as never);

  render(<Page />);
  fireEvent.click(await screen.findByRole("button", { name: "参考岗位 · 0 条依据" }));
  const panel = screen.getByRole("dialog", { name: "这条回答的依据" });
  fireEvent.click(within(panel).getByRole("button", { name: "纠正" }));
  fireEvent.change(within(panel).getByRole("textbox", { name: "纠正skill.python" }), { target: { value: "我会 Python 和 FastAPI" } });
  fireEvent.click(within(panel).getByRole("button", { name: "保存纠正" }));
  await waitFor(() => expect(api.updateAgentMemory).toHaveBeenCalledWith("memory-1", { content: "我会 Python 和 FastAPI", user_confirmed: true }));
});
