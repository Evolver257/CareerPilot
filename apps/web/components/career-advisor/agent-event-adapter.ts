import type { CareerAdvisorMessage } from "../../lib/api";

export type AgentStage =
  | "understanding"
  | "planning"
  | "memory"
  | "searching"
  | "analyzing"
  | "evidence"
  | "writing"
  | "finalizing"
  | "completed"
  | "failed"
  | "cancelled";

export type AgentRunStatus = "running" | "completed" | "failed" | "cancelled";
export type AgentConnectionState = "connected" | "reconnecting" | "recovered" | "offline";

export type AgentToolState = {
  id: string;
  tool: string;
  displayName: string;
  status: "running" | "completed" | "failed";
  inputSummary: string;
  resultSummary: string;
  durationMs: number | null;
  retryable: boolean;
};

export type AgentRunState = {
  runId: string;
  status: AgentRunStatus;
  stage: AgentStage;
  /** Stages that have actually occurred, in event order. */
  stageHistory: AgentStage[];
  label: string;
  detail: string;
  startedAt: string;
  completedAt: string | null;
  latencyMs: number | null;
  lastEventId: string | null;
  seenEventIds: string[];
  tools: AgentToolState[];
  sampleCount: number;
  evidenceCount: number;
  plannedTools: string[];
  answerStarted: boolean;
  connection: AgentConnectionState;
  reconnectAttempt: number;
};

export type AgentRunEvent = {
  id: string;
  type: string;
  runId: string;
  payload: Record<string, unknown>;
  createdAt: string;
};

export const AGENT_STAGE_ORDER: AgentStage[] = [
  "understanding",
  "planning",
  "memory",
  "searching",
  "analyzing",
  "evidence",
  "writing",
  "finalizing",
];

export const AGENT_STAGE_LABELS: Record<AgentStage, string> = {
  understanding: "理解问题",
  planning: "制定分析步骤",
  memory: "读取职业偏好和简历",
  searching: "检索岗位知识库",
  analyzing: "分析岗位技能要求",
  evidence: "整理岗位证据",
  writing: "组织职业建议",
  finalizing: "检查回答和引用",
  completed: "已完成",
  failed: "执行失败",
  cancelled: "已停止",
};

const TOOL_DISPLAY_NAMES: Record<string, string> = {
  search_job_knowledge: "检索岗位知识库",
  aggregate_job_market: "统计岗位市场需求",
  analyze_resume_gap: "分析简历能力差距",
  retrieve_career_memory: "读取职业偏好",
  search_jobs: "查找相关岗位",
  collect_jobs_online: "启动招聘平台岗位采集",
  compare_roles: "比较岗位方向",
  compare_role_profiles: "比较岗位方向",
  explain_skill_demand: "分析技能需求",
  build_learning_roadmap: "生成学习路线",
  recommend_jobs: "推荐相关岗位",
  deep_dive_skill_requirements: "深挖技能要求",
  tool_planner: "制定工具使用计划",
};

export function displayToolName(tool: string) {
  return TOOL_DISPLAY_NAMES[tool] ?? "处理岗位信息";
}

function text(value: unknown, fallback = "") {
  return typeof value === "string" && value.trim() ? value.trim() : fallback;
}

function number(value: unknown) {
  return typeof value === "number" && Number.isFinite(value) ? value : 0;
}

function executionRecord(payload: Record<string, unknown>) {
  const governance = payload.governance;
  if (!governance || typeof governance !== "object") return null;
  const execution = (governance as Record<string, unknown>).execution;
  return execution && typeof execution === "object"
    ? (execution as Record<string, unknown>)
    : null;
}

function executionStatus(payload: Record<string, unknown>) {
  const execution = executionRecord(payload);
  return text(execution?.execution_status ?? execution?.status).toUpperCase();
}

const BUSINESS_TOOL_NAMES = new Set([
  "search_jobs",
  "collect_jobs_online",
  "search_job_knowledge",
  "aggregate_job_market",
  "explain_skill_demand",
  "build_learning_roadmap",
  "analyze_resume_gap",
  "compare_role_profiles",
  "recommend_jobs",
  "deep_dive_skill_requirements",
  "retrieve_career_memory",
]);

/** Only governed business tools represent an actual runtime invocation. */
export function isExecutedBusinessToolTrace(payload: Record<string, unknown>) {
  const execution = executionRecord(payload);
  const tool = text(payload.tool);
  // Older live events did not include the governance envelope. Keep those
  // events compatible, but only for the explicitly registered business tools.
  if (!execution) return BUSINESS_TOOL_NAMES.has(tool) || tool.startsWith("mcp__");
  return executionStatus(payload) !== "REJECTED";
}

function traceDurationMs(payload: Record<string, unknown>) {
  return number(payload.duration_ms ?? executionRecord(payload)?.latency_ms) || null;
}

function safeToolInputSummary(payload: Record<string, unknown>) {
  const input = payload.input;
  if (!input || typeof input !== "object") return "已按当前咨询条件执行";
  const value = input as Record<string, unknown>;
  const filters = value.filters;
  if (filters && typeof filters === "object") {
    const filterValue = filters as Record<string, unknown>;
    const parts = [
      Array.isArray(filterValue.cities) && filterValue.cities.length ? `城市 ${filterValue.cities.join("、")}` : "",
      text(filterValue.education) ? `学历 ${text(filterValue.education)}` : "",
      text(filterValue.experience) ? `经验 ${text(filterValue.experience)}` : "",
    ].filter(Boolean);
    return parts.length ? parts.join(" · ") : "已按当前咨询条件执行";
  }
  return "已按当前咨询条件执行";
}

function safeToolResultSummary(payload: Record<string, unknown>) {
  const output = payload.output;
  if (!output || typeof output !== "object") return "已完成处理";
  const value = output as Record<string, unknown>;
  const count = number(value.sample_count ?? value.count ?? value.citation_count);
  const evidence = number(value.evidence_count ?? value.citations ?? value.citation_count);
  if (count > 0 && evidence > 0) return `找到 ${count} 个岗位，整理 ${evidence} 条证据`;
  if (count > 0) return `处理 ${count} 条岗位样本`;
  if (evidence > 0) return `整理 ${evidence} 条有效证据`;
  const status = text(value.status ?? value.semantic_status);
  return status ? `状态：${status}` : "已完成处理";
}

export function createAgentRun(runId: string, startedAt = new Date().toISOString()): AgentRunState {
  return {
    runId,
    status: "running",
    stage: "understanding",
    stageHistory: ["understanding"],
    label: AGENT_STAGE_LABELS.understanding,
    detail: "正在理解你的问题",
    startedAt,
    completedAt: null,
    latencyMs: null,
    lastEventId: null,
    seenEventIds: [],
    tools: [],
    sampleCount: 0,
    evidenceCount: 0,
    plannedTools: [],
    answerStarted: false,
    connection: "connected",
    reconnectAttempt: 0,
  };
}

export function eventFromCareerAdvisor(
  eventType: string,
  payload: Record<string, unknown>,
  fallbackRunId: string,
  sequence: number,
): AgentRunEvent {
  const runId = text(payload.run_id ?? payload.message_id ?? payload.id, fallbackRunId);
  const id = text(payload.event_id, `${eventType}:${runId}:${sequence}`);
  return {
    id,
    type: eventType,
    runId,
    payload,
    createdAt: text(payload.created_at, new Date().toISOString()),
  };
}

function stageForEvent(event: AgentRunEvent): AgentStage | null {
  const stage = text(event.payload.stage);
  if (event.type === "stage_changed") {
    if (stage === "understanding" || stage === "planning" || stage === "memory" || stage === "searching" || stage === "analyzing" || stage === "evidence" || stage === "writing" || stage === "finalizing") return stage;
  }
  if (event.type === "intent_detected") return "planning";
  if (event.type === "retrieval_status") return stage === "query_analysis" || stage === "retrieval_planning" ? "planning" : stage === "memory" ? "memory" : "searching";
  if (event.type === "evidence_status") return "evidence";
  if (event.type === "facts_ready") return "analyzing";
  if (event.type === "delta") return "writing";
  if (event.type === "message_completed" || event.type === "message_state") return "completed";
  if (event.type === "message_failed") return "failed";
  if (event.type === "message_cancelled") return "cancelled";
  return null;
}

export function reduceAgentRun(previous: AgentRunState, event: AgentRunEvent): AgentRunState {
  if (previous.seenEventIds.includes(event.id)) return previous;
  const seenEventIds = [...previous.seenEventIds, event.id].slice(-160);
  const next: AgentRunState = { ...previous, seenEventIds, lastEventId: event.id, connection: "connected" };
  const stage = stageForEvent(event);
  if (stage) {
    next.stage = stage;
    // The stage title is owned by the frontend so backend wording cannot
    // accidentally expose internal reasoning or make the UI inconsistent.
    next.label = AGENT_STAGE_LABELS[stage];
    next.detail = text(event.payload.detail ?? event.payload.label, next.label);
    if (!(["completed", "failed", "cancelled"] as AgentStage[]).includes(stage)) {
      const lastVisited = next.stageHistory[next.stageHistory.length - 1];
      if (lastVisited !== stage) next.stageHistory = [...next.stageHistory, stage];
    }
    if (stage === "completed") {
      next.status = "completed";
      next.completedAt = event.createdAt;
    } else if (stage === "failed") {
      next.status = "failed";
      next.completedAt = event.createdAt;
    } else if (stage === "cancelled") {
      next.status = "cancelled";
      next.completedAt = event.createdAt;
    }
  }
  if (event.type === "message_started") {
    next.status = "running";
    next.stage = "understanding";
    next.stageHistory = ["understanding"];
    next.label = AGENT_STAGE_LABELS.understanding;
    next.startedAt = event.createdAt;
  }
  if (event.type === "intent_detected") {
    next.plannedTools = Array.isArray(event.payload.planned_tools)
      ? event.payload.planned_tools.filter((item): item is string => typeof item === "string")
      : next.plannedTools;
  }
  if (event.type === "facts_ready") next.sampleCount = number(event.payload.sample_count);
  if (event.type === "evidence_status") next.evidenceCount = number(event.payload.evidence_count ?? event.payload.citation_count) || next.evidenceCount;
  if (event.type === "delta") next.answerStarted = true;
  if (event.type === "tool_started") {
    const tool = text(event.payload.tool, "unknown");
    const id = text(event.payload.tool_call_id, `${tool}:${event.id}`);
    next.tools = [...next.tools.filter((item) => item.id !== id), {
      id,
      tool,
      displayName: text(event.payload.display_name, displayToolName(tool)),
      status: "running",
      inputSummary: text(event.payload.input_summary, "已按当前咨询条件执行"),
      resultSummary: "正在处理",
      durationMs: null,
      retryable: false,
    }];
  }
  if (event.type === "tool_finished" || event.type === "tool_completed" || event.type === "tool_failed") {
    const trace = event.payload;
    if (!isExecutedBusinessToolTrace(trace)) return next;
    const tool = text(trace.tool, "unknown");
    const id = text(trace.tool_call_id, `${tool}:${event.id}`);
    const failed = event.type === "tool_failed" || ["FAILED", "TIMEOUT"].includes(executionStatus(trace));
    const existing = next.tools.find((item) => item.id === id);
    next.tools = [...next.tools.filter((item) => item.id !== id), {
      id,
      tool,
      displayName: text(trace.display_name, displayToolName(tool)),
      status: failed ? "failed" : "completed",
      inputSummary: existing?.inputSummary ?? safeToolInputSummary(trace),
      resultSummary: failed ? text(trace.error_summary, "执行失败") : text(trace.result_summary, safeToolResultSummary(trace)),
      durationMs: traceDurationMs(trace),
      retryable: trace.retryable === true,
    }];
  }
  if (event.type === "message_failed") next.detail = text(event.payload.error, "职业顾问生成失败");
  if (event.type === "message_cancelled") next.detail = "已保留已经生成的内容";
  return next;
}

export function agentRunFromMessage(message: CareerAdvisorMessage): AgentRunState {
  const metadata = message.answer_metadata ?? {};
  const status: AgentRunStatus = message.status === "FAILED" ? "failed" : message.status === "CANCELLED" ? "cancelled" : message.status === "RUNNING" ? "running" : "completed";
  const stage: AgentStage = status === "failed" ? "failed" : status === "cancelled" ? "cancelled" : status === "running" ? "writing" : "completed";
  const run = createAgentRun(message.id, message.created_at);
  run.status = status;
  run.stage = stage;
  run.stageHistory = [message.content ? "writing" : "understanding"];
  run.label = status === "completed" ? AGENT_STAGE_LABELS.completed : status === "failed" ? AGENT_STAGE_LABELS.failed : status === "cancelled" ? AGENT_STAGE_LABELS.cancelled : "正在生成回答";
  run.detail = text(message.error_message, run.label);
  run.completedAt = status === "running" ? null : message.updated_at;
  run.latencyMs = number(message.latency_ms) || null;
  run.sampleCount = number(metadata.sample_count);
  run.evidenceCount = number(metadata.citation_count) || message.citations.length;
  run.plannedTools = Array.isArray(metadata.planned_tools) ? metadata.planned_tools.filter((item): item is string => typeof item === "string") : [];
  run.answerStarted = Boolean(message.content);
  run.tools = message.tool_trace.filter(isExecutedBusinessToolTrace).map((trace, index) => {
    const tool = text(trace.tool, "unknown");
    return {
      id: text(trace.tool_call_id, `${tool}:${index}`),
      tool,
      displayName: displayToolName(tool),
      status: "completed",
      inputSummary: safeToolInputSummary(trace),
      resultSummary: safeToolResultSummary(trace),
      durationMs: traceDurationMs(trace),
      retryable: false,
    };
  });
  return run;
}
