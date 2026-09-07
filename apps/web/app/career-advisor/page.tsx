"use client";

import Link from "next/link";
import { useCallback, useEffect, useRef, useState, type FormEvent } from "react";

import { MarkdownContent } from "../../components/markdown-content";
import { AdvisorDialog } from "../../components/advisor-dialog";
import { shouldFollowMessages, splitAdvisorAnswer } from "../../lib/advisor-presentation";
import {
  cancelCareerAdvisorMessage,
  cancelCareerAdvisorApplication,
  confirmCareerAdvisorApplication,
  getCareerAdvisorApplicationProgress,
  createCareerAdvisorSession,
  deleteCareerAdvisorSession,
  getCareerAdvisorSession,
  getCareerAdvisorSessions,
  getKnowledgeHealth,
  type KnowledgeHealth,
  getResumes,
  createKnowledgeIndexRun,
  prepareCareerAdvisorApplication,
  streamCareerAdvisorMessage,
  streamRegenerateCareerAdvisorMessage,
  updateCareerAdvisorSession,
  type CareerAdvisorIntent,
  type CareerAdvisorJobCandidate,
  type CareerAdvisorMessage,
  type CareerAdvisorSession,
  type CareerAdvisorUiAction,
  type JobKnowledgeFilters,
  type Resume,
} from "../../lib/api";

const intentLabels: Record<string, string> = {
  market_research: "市场研究",
  learning_roadmap: "学习路线",
  resume_gap: "简历差距",
  role_comparison: "岗位对比",
  job_recommendation: "岗位推荐",
  salary_analysis: "薪资分析",
  skill_analysis: "技能需求",
  follow_up: "追问",
  general_career_chat: "职业咨询",
};

const statusLabels: Record<string, string> = {
  RUNNING: "生成中",
  COMPLETED: "已完成",
  FAILED: "生成失败",
  CANCELLED: "已停止",
};

const generationStages = [
  { id: "understanding", label: "理解目标" },
  { id: "searching", label: "检索岗位" },
  { id: "analyzing", label: "分析需求" },
  { id: "writing", label: "生成建议" },
  { id: "finalizing", label: "整理引用" },
];

const quickPrompts = [
  { title: "规划学习方向", prompt: "我想学习 AI Agent，需要掌握哪些技术栈？", icon: "✦" },
  { title: "了解岗位市场", prompt: "结合岗位数据，分析 RAG 实习岗位的薪资和学历要求。", icon: "⌁" },
  { title: "分析简历差距", prompt: "我的简历距离后端开发岗位还缺哪些能力？", icon: "◎" },
  { title: "对比职业方向", prompt: "对比 Java 后端和大模型应用开发，我更适合哪个方向？", icon: "⇄" },
];

function emptyFilters(): JobKnowledgeFilters {
  return {
    cities: [],
    education: null,
    experience: null,
    job_types: [],
    platform: null,
    salary_floor: null,
    salary_ceiling: null,
    published_after: null,
    published_before: null,
  };
}

function cloneFilters(filters: JobKnowledgeFilters): JobKnowledgeFilters {
  return {
    ...filters,
    cities: [...(filters.cities ?? [])],
    job_types: [...(filters.job_types ?? [])],
  };
}

function metadataText(value: unknown, fallback = "") {
  return typeof value === "string" && value.trim() ? value : fallback;
}

function metadataNumber(value: unknown) {
  return typeof value === "number" && Number.isFinite(value) ? value : 0;
}

function formatDate(value: string) {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "刚刚";
  return date.toLocaleDateString("zh-CN", { month: "short", day: "numeric" });
}

function formatFilterDate(value: string | null) {
  return value ? value.slice(0, 10) : "";
}

function toIsoDate(value: string) {
  return value ? `${value}T00:00:00Z` : null;
}

function localUserMessage(sessionId: string, content: string): CareerAdvisorMessage {
  return {
    id: `local-user-${Date.now()}`,
    session_id: sessionId,
    role: "user",
    content,
    status: "COMPLETED",
    intent: null,
    model_provider: null,
    model_name: null,
    token_usage: {},
    tool_trace: [],
    answer_metadata: {},
    latency_ms: 0,
    error_message: null,
    created_at: new Date().toISOString(),
    updated_at: new Date().toISOString(),
    citations: [],
  };
}

function emptyAssistantMessage(sessionId: string, id: string): CareerAdvisorMessage {
  return {
    id,
    session_id: sessionId,
    role: "assistant",
    content: "",
    status: "RUNNING",
    intent: null,
    model_provider: null,
    model_name: null,
    token_usage: {},
    tool_trace: [],
    answer_metadata: {},
    latency_ms: 0,
    error_message: null,
    citations: [],
    created_at: new Date().toISOString(),
    updated_at: new Date().toISOString(),
  };
}

function statusClass(status: string) {
  if (status === "COMPLETED") return "bg-emerald-50 text-emerald-700";
  if (status === "FAILED") return "bg-rose-50 text-rose-700";
  if (status === "CANCELLED") return "bg-amber-50 text-amber-700";
  return "bg-indigo-50 text-indigo-700";
}

function filterSummary(value: unknown) {
  if (!value || typeof value !== "object") return "未设置";
  const filters = value as Record<string, unknown>;
  const parts: string[] = [];
  if (Array.isArray(filters.cities) && filters.cities.length) parts.push(`城市：${filters.cities.join("、")}`);
  if (typeof filters.education === "string" && filters.education) parts.push(`学历：${filters.education}`);
  if (typeof filters.experience === "string" && filters.experience) parts.push(`经验：${filters.experience}`);
  if (Array.isArray(filters.job_types) && filters.job_types.length) parts.push(`类型：${filters.job_types.join("、")}`);
  if (typeof filters.platform === "string" && filters.platform) parts.push(`平台：${filters.platform}`);
  return parts.join(" · ") || "未设置额外筛选";
}

function filterCount(filters: JobKnowledgeFilters) {
  return [
    filters.cities.length > 0,
    Boolean(filters.education),
    Boolean(filters.experience),
    filters.job_types.length > 0,
    Boolean(filters.platform),
    filters.salary_floor != null || filters.salary_ceiling != null,
    Boolean(filters.published_after) || Boolean(filters.published_before),
  ].filter(Boolean).length;
}

function followUpPrompts(message: CareerAdvisorMessage | null) {
  if (!message) return [];
  if (message.intent === "resume_gap") {
    return ["把技能缺口按优先级排序", "给我制定 12 周补齐计划", "查看适合我的相关岗位"];
  }
  if (message.intent === "role_comparison") {
    return ["结合我的简历给出选择建议", "分别给出学习路线", "查看两个方向的相关岗位"];
  }
  return ["结合我的简历分析差距", "给我制定 12 周学习路线", "查看这个方向的相关岗位"];
}

function formatMetadataDate(value: unknown) {
  if (typeof value !== "string" || !value) return "未注明";
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? value : date.toLocaleString("zh-CN", { dateStyle: "medium", timeStyle: "short" });
}

function messageUiAction(message: CareerAdvisorMessage): CareerAdvisorUiAction | null {
  const value = message.ui_action ?? message.answer_metadata.ui_action;
  return value && typeof value === "object" && typeof (value as Record<string, unknown>).type === "string"
    ? value as CareerAdvisorUiAction
    : null;
}

function presentationMarkdown(value: string) {
  const lines = value.split("\n");
  const result: string[] = [];
  let skippingEmbeddedCitations = false;
  for (const line of lines) {
    if (line.trim() === "## 代表性岗位引用") {
      skippingEmbeddedCitations = true;
      continue;
    }
    if (skippingEmbeddedCitations && line.startsWith("## ")) {
      skippingEmbeddedCitations = false;
    }
    if (skippingEmbeddedCitations) continue;
    if (line.startsWith("- 当前过滤条件：")) continue;
    if (line.startsWith("- 数据更新时间：")) {
      result.push(`- 数据更新：${formatMetadataDate(line.slice("- 数据更新时间：".length))}`);
      continue;
    }
    result.push(line);
  }
  return result.join("\n").replace(/\n{3,}/g, "\n\n").trim();
}

function tokenUsageSummary(value: unknown) {
  if (!value || typeof value !== "object") return "";
  const usage = value as Record<string, unknown>;
  const input = metadataNumber(usage.input_tokens ?? usage.prompt_tokens);
  const output = metadataNumber(usage.output_tokens ?? usage.completion_tokens);
  const total = metadataNumber(usage.total_tokens) || input + output;
  return total > 0 ? `输入 ${input.toLocaleString()} · 输出 ${output.toLocaleString()} · 合计 ${total.toLocaleString()}` : "";
}

function EvidenceContent({ message }: { message: CareerAdvisorMessage }) {
  const factSource = metadataText(message.answer_metadata.fact_source);
  const adviceSource = metadataText(message.answer_metadata.advice_source);
  const plannerSource = metadataText(message.answer_metadata.planner_source, "rules");
  const plannedTools = Array.isArray(message.answer_metadata.planned_tools)
    ? message.answer_metadata.planned_tools.filter((item): item is string => typeof item === "string")
    : [];
  const sampleCount = metadataNumber(message.answer_metadata.sample_count);
  const dataSufficient = message.answer_metadata.data_sufficient === true;
  const skillDeepDiveCount = metadataNumber(message.answer_metadata.skill_deep_dive_count);
  const skillEvidenceCount = metadataNumber(message.answer_metadata.skill_evidence_count);
  const skillFocus = Array.isArray(message.answer_metadata.skill_focus)
    ? message.answer_metadata.skill_focus.filter((item): item is string => typeof item === "string" && Boolean(item.trim()))
    : [];
  const ragMode = metadataText(message.answer_metadata.rag_mode);
  const ragStatus = metadataText(message.answer_metadata.rag_knowledge_status);
  const ragConfidence = metadataText(message.answer_metadata.rag_confidence);
  const ragIterations = metadataNumber(message.answer_metadata.rag_iterations);
  const ragQueryCount = metadataNumber(message.answer_metadata.rag_query_count);
  const ragCandidateCount = metadataNumber(message.answer_metadata.rag_candidate_count);
  const ragRerankedCount = metadataNumber(message.answer_metadata.rag_reranked_count);
  const ragEvidenceCount = metadataNumber(message.answer_metadata.rag_evidence_count);
  const ragCoverage = metadataNumber(message.answer_metadata.rag_coverage_score);
  const ragMaxRelevance = metadataNumber(message.answer_metadata.rag_max_relevance_score);
  const hasRagRelevance = typeof message.answer_metadata.rag_max_relevance_score === "number";
  const ragPlannerSource = metadataText(message.answer_metadata.rag_planner_source, "rules");
  const ragReflectionIterations = metadataNumber(message.answer_metadata.rag_reflection_iterations);
  const ragCoverageBefore = metadataNumber(message.answer_metadata.rag_coverage_before);
  const ragCoverageAfter = metadataNumber(message.answer_metadata.rag_coverage_after);
  const ragStopReason = metadataText(message.answer_metadata.rag_stop_reason);
  const ragRepairActions = Array.isArray(message.answer_metadata.rag_repair_actions)
    ? message.answer_metadata.rag_repair_actions.filter((item): item is string => typeof item === "string")
    : [];
  const answerReflection = message.answer_metadata.rag_answer_reflection;
  const answerWasRepaired = message.answer_metadata.rag_answer_repaired === true;
  const ragMissing = Array.isArray(message.answer_metadata.rag_missing_information)
    ? message.answer_metadata.rag_missing_information.filter((item): item is string => typeof item === "string")
    : [];
  const warnings = Array.isArray(message.answer_metadata.warnings)
    ? message.answer_metadata.warnings.filter((item): item is string => typeof item === "string")
    : [];
  const tools = message.tool_trace
    .map((trace) => metadataText(trace.tool))
    .filter(Boolean);
  const tokenUsage = tokenUsageSummary(message.token_usage);
  return (
    <div className="space-y-4">
      <div className="grid grid-cols-2 gap-2">
        <div className="rounded-xl bg-slate-50 p-3"><p className="text-xs text-slate-500">岗位样本</p><p className="mt-1 text-lg font-semibold text-slate-900">{sampleCount}</p></div>
        <div className="rounded-xl bg-slate-50 p-3"><p className="text-xs text-slate-500">数据更新时间</p><p className="mt-1 text-xs font-medium leading-5 text-slate-800">{formatMetadataDate(message.answer_metadata.data_as_of)}</p></div>
      </div>
      <div className="flex flex-wrap gap-2 text-xs">
        <span className="rounded-full bg-emerald-50 px-2.5 py-1 font-medium text-emerald-700">{factSource === "database" ? "来自岗位数据" : "暂无岗位数据"}</span>
        <span className="rounded-full bg-indigo-50 px-2.5 py-1 font-medium text-indigo-700">{adviceSource === "llm" ? "AI 整理" : "规则整理"}</span>
        <span className={`rounded-full px-2.5 py-1 font-medium ${dataSufficient ? "bg-emerald-50 text-emerald-700" : "bg-amber-50 text-amber-700"}`}>{dataSufficient ? "样本充足" : "样本较少"}</span>
        {skillDeepDiveCount > 0 && <span className="rounded-full bg-violet-50 px-2.5 py-1 font-medium text-violet-700">JD 深挖 {skillDeepDiveCount} 项技能</span>}
      </div>
      {skillDeepDiveCount > 0 && <div className="rounded-xl border border-violet-200 bg-violet-50/70 p-3 text-xs leading-5 text-violet-900 dark:border-violet-900/70 dark:bg-violet-950/30 dark:text-violet-100"><p className="font-semibold">岗位能力地图已生成</p><p className="mt-1">已针对 {skillFocus.join("、") || `${skillDeepDiveCount} 项重点技能`} 二次检索 JD，整理为能力要求、学习顺序和项目证明方式。</p><p className="mt-1 text-violet-700 dark:text-violet-300">补充证据片段：{skillEvidenceCount} 条</p></div>}
      {ragMode === "agentic" && <div className="rounded-xl border border-cyan-200 bg-cyan-50/70 p-3 text-xs leading-5 text-cyan-950 dark:border-cyan-900/70 dark:bg-cyan-950/30 dark:text-cyan-100"><div className="flex items-center justify-between gap-2"><p className="font-semibold">Agentic RAG 证据链</p><span className="rounded-full bg-white/80 px-2 py-0.5 font-medium text-cyan-700 dark:bg-cyan-950 dark:text-cyan-300">{ragStatus || "unknown"} · {ragConfidence || "low"}</span></div><p className="mt-2">{ragIterations} 轮检索 · {ragQueryCount} 个查询 · {ragCandidateCount} 条候选 · {ragRerankedCount} 条重排 · {ragEvidenceCount} 条证据</p><div className="mt-1 flex flex-wrap gap-x-3 gap-y-1 text-cyan-700 dark:text-cyan-300"><span>证据覆盖度：{Math.round(ragCoverage * 100)}%</span>{hasRagRelevance && <span>最高直接相关性：{Math.round(ragMaxRelevance * 100)}%</span>}{ragPlannerSource && <span>规划：{ragPlannerSource.startsWith("llm") ? "LLM" : "规则兜底"}</span>}</div>{ragReflectionIterations > 0 && <p className="mt-1 text-cyan-700 dark:text-cyan-300">已反思修复 {ragReflectionIterations} 次{ragRepairActions.length > 0 ? ` · ${ragRepairActions.join("、")}` : ""} · 覆盖度 {Math.round(ragCoverageBefore * 100)}% → {Math.round(ragCoverageAfter * 100)}%</p>}{ragStopReason && <p className="mt-1 text-slate-600 dark:text-slate-300">停止原因：{ragStopReason}</p>}{ragMissing.length > 0 && <p className="mt-1 text-amber-700 dark:text-amber-300">尚未覆盖：{ragMissing.join("、")}</p>}</div>}
      {answerReflection !== undefined && answerReflection !== null && typeof answerReflection === "object" && <div className={`rounded-xl border p-3 text-xs leading-5 ${answerWasRepaired ? "border-amber-200 bg-amber-50/70 text-amber-900 dark:border-amber-900/70 dark:bg-amber-950/30 dark:text-amber-100" : "border-slate-200 bg-slate-50 text-slate-600 dark:border-slate-700 dark:bg-slate-900/60 dark:text-slate-300"}`}><p className="font-semibold">回答可靠性校验</p><p className="mt-1">{answerWasRepaired ? "发现缺少直接证据的表述，已在回答末尾标注待核实内容。" : "已完成回答断言与岗位证据的一致性检查。"}</p></div>}
      <div className="rounded-xl border border-slate-200 p-3 text-xs leading-5 text-slate-600"><span className="font-semibold text-slate-800">统计口径：</span>{filterSummary(message.answer_metadata.filters)}</div>
      {warnings.length > 0 && <div className="rounded-xl border border-amber-200 bg-amber-50 p-3 text-xs leading-5 text-amber-800"><p className="font-semibold">数据质量提示</p><ul className="mt-1 list-disc space-y-1 pl-4">{warnings.map((warning) => <li key={warning}>{warning}</li>)}</ul></div>}
      {(plannedTools.length > 0 || tools.length > 0 || tokenUsage) && <details className="rounded-xl border border-slate-200 p-3"><summary className="cursor-pointer text-xs font-semibold text-slate-700">运行详情</summary><div className="mt-3 space-y-2 text-xs leading-5 text-slate-500"><p>工具决策：{plannerSource.startsWith("llm") ? "LLM" : "规则"}</p>{plannedTools.length > 0 && <p>规划工具：{plannedTools.join("、")}</p>}{tools.length > 0 && <p>执行工具：{tools.join("、")}</p>}{tokenUsage && <p>模型消耗：{tokenUsage}</p>}</div></details>}
      <div>
        <p className="text-xs font-semibold text-slate-800">岗位引用 · {message.citations.length} 条</p>
        {message.citations.length === 0 && <p className="mt-2 text-xs leading-5 text-slate-500">本次没有召回可引用的岗位片段。</p>}
        <div className="mt-2 space-y-3">
          {message.citations.map((citation) => {
            const title = metadataText(citation.metadata.title, "未命名岗位");
            const company = metadataText(citation.metadata.company, "公司未注明");
            const location = metadataText(citation.metadata.location);
            const section = metadataText(citation.metadata.section_type, "岗位信息");
            return (
              <div className="rounded-xl border border-indigo-100 bg-white p-3 dark:bg-slate-900" key={citation.id}>
                <div className="flex flex-wrap items-center gap-2 text-xs text-slate-500"><span className="font-semibold text-indigo-700">[{citation.citation_index}]</span><span>{section}</span><span>·</span><span>{company}</span>{location && <><span>·</span><span>{location}</span></>}</div>
                <p className="mt-1 text-sm font-medium text-slate-800">{title}</p>
                <p className="mt-2 text-sm leading-6 text-slate-600">{citation.evidence}</p>
                {citation.job_id && <Link className="mt-2 inline-flex text-xs font-medium text-indigo-600 hover:text-indigo-800" href={`/jobs/${citation.job_id}`}>查看岗位详情 →</Link>}
              </div>
            );
          })}
        </div>
      </div>
    </div>
  );
}

function SessionList({
  sessions,
  selectedSessionId,
  sessionTotal,
  loading,
  loadingMore,
  onSelect,
  onLoadMore,
}: {
  sessions: CareerAdvisorSession[];
  selectedSessionId: string | null;
  sessionTotal: number;
  loading: boolean;
  loadingMore: boolean;
  onSelect: (id: string) => void;
  onLoadMore: () => void;
}) {
  const [search, setSearch] = useState("");
  const visibleSessions = sessions.filter((session) => session.title.toLocaleLowerCase().includes(search.trim().toLocaleLowerCase()));
  return <>
    <div className="flex items-center justify-between px-2 py-2">
      <span className="text-sm font-semibold text-slate-900">咨询记录</span>
      <span className="text-xs text-slate-400">{sessions.length}/{sessionTotal}</span>
    </div>
    <input aria-label="搜索已加载咨询" placeholder="搜索已加载咨询…" value={search} onChange={(event) => setSearch(event.target.value)} className="my-2 w-full rounded-xl border border-slate-200 bg-white px-3 py-2 text-sm" />
    <div className="mt-2 space-y-1">
      {loading && <div aria-label="正在加载咨询记录" className="space-y-2 px-1 py-2">
        {[0, 1, 2].map((item) => <div className="h-16 animate-pulse rounded-xl bg-slate-100" key={item} />)}
      </div>}
      {!loading && sessions.length === 0 && <p className="px-2 py-8 text-center text-sm leading-6 text-slate-400">还没有咨询记录<br />开始第一次职业咨询吧</p>}
      {search && visibleSessions.length === 0 && <p className="p-3 text-sm text-slate-500">未找到匹配的咨询，可加载更多记录后继续查找。</p>}
      {visibleSessions.map((session) => {
        const active = session.id === selectedSessionId;
        const lastMessage = [...session.messages].reverse().find((message) => message.role === "user");
        return (
          <button className={`w-full rounded-xl px-3 py-3 text-left transition-colors duration-150 ${active ? "bg-indigo-50 text-indigo-800" : "text-slate-600 hover:bg-slate-50"}`} key={session.id} onClick={() => onSelect(session.id)} type="button">
            <div className="flex items-start justify-between gap-2">
              <span className="truncate text-sm font-medium">{session.title}</span>
              <span className="shrink-0 text-[11px] text-slate-400">{formatDate(session.updated_at)}</span>
            </div>
            {lastMessage && <p className="mt-1 truncate text-xs text-slate-400">{lastMessage.content}</p>}
          </button>
        );
      })}
      {sessions.length < sessionTotal && <button className="w-full rounded-xl border border-slate-200 px-3 py-2 text-xs font-medium text-slate-500 transition hover:border-indigo-300 hover:text-indigo-700 disabled:opacity-50" disabled={loadingMore} onClick={onLoadMore} type="button">{loadingMore ? "加载中…" : "加载更多会话"}</button>}
    </div>
  </>;
}

function GenerationProgress({ stage, sampleCount, statusLabel }: { stage: string; sampleCount: number; statusLabel: string }) {
  const activeIndex = Math.max(0, generationStages.findIndex((item) => item.id === stage));
  return <div className="advisor-stream-status mb-4 rounded-2xl border border-indigo-200 p-3">
    <div className="flex flex-wrap items-center justify-between gap-2">
      <div className="flex items-center gap-2 text-sm font-semibold text-indigo-800"><span className="relative flex h-2.5 w-2.5"><span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-indigo-400 opacity-40" /><span className="relative inline-flex h-2.5 w-2.5 rounded-full bg-indigo-500" /></span>{statusLabel || generationStages[activeIndex]?.label || "正在生成"}</div>
      {sampleCount > 0 && <span className="text-xs text-indigo-600">已分析 {sampleCount} 个相关岗位</span>}
    </div>
    <div className="mt-3 grid grid-cols-5 gap-1.5" aria-label="回答生成进度">
      {generationStages.map((item, index) => <div key={item.id}><div className={`h-1 rounded-full transition-colors duration-300 ${index <= activeIndex ? "bg-indigo-500" : "bg-indigo-100 dark:bg-slate-700"}`} /><p className={`mt-1 hidden text-center text-[10px] sm:block ${index <= activeIndex ? "text-indigo-700" : "text-slate-400"}`}>{item.label}</p></div>)}
    </div>
  </div>;
}

function JobSearchActionCard({
  action,
  sessionId,
  messageId,
  resumeId,
  onUpdate,
  onError,
}: {
  action: CareerAdvisorUiAction;
  sessionId: string;
  messageId: string;
  resumeId: string | null;
  onUpdate: (action: CareerAdvisorUiAction) => void;
  onError: (message: string) => void;
}) {
  const jobs = action.jobs ?? [];
  const initialSelection = action.default_selected_job_ids ?? jobs.filter((job) => job.default_selected).map((job) => job.id);
  const [selected, setSelected] = useState<Set<string>>(() => new Set(initialSelection));
  const [submitting, setSubmitting] = useState(false);
  const toggle = (jobId: string) => setSelected((current) => {
    const next = new Set(current);
    if (next.has(jobId)) next.delete(jobId); else next.add(jobId);
    return next;
  });
  async function prepare() {
    if (selected.size === 0 || submitting) return;
    setSubmitting(true);
    try {
      const result = await prepareCareerAdvisorApplication(sessionId, {
        message_id: messageId,
        job_ids: [...selected],
        resume_id: resumeId,
      });
      onUpdate(result.ui_action);
    } catch (reason) {
      onError(reason instanceof Error ? reason.message : "无法准备投递确认");
    } finally {
      setSubmitting(false);
    }
  }
  return (
    <section className="mt-4 rounded-2xl border border-indigo-200 bg-indigo-50/60 p-4 dark:border-indigo-900/70 dark:bg-indigo-950/30" aria-label="岗位候选">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div><h3 className="text-sm font-semibold text-slate-900 dark:text-slate-100">{action.title ?? "岗位候选"}</h3><p className="mt-1 text-xs leading-5 text-slate-500 dark:text-slate-400">{action.summary ?? "已结合当前咨询条件筛选"}</p></div>
        <span className="rounded-full bg-white px-2.5 py-1 text-xs font-semibold text-indigo-700 shadow-sm dark:bg-slate-900 dark:text-indigo-300">已选 {selected.size}/{jobs.length}</span>
      </div>
      <div className="mt-3 space-y-2">
        {jobs.slice(0, 30).map((job: CareerAdvisorJobCandidate) => {
          const lowMatch = (action.low_match_job_ids ?? []).includes(job.id);
          const expired = (action.expired_job_ids ?? []).includes(job.id);
          return <label className={`flex cursor-pointer gap-3 rounded-xl border bg-white p-3 transition-colors dark:bg-slate-900 ${selected.has(job.id) ? "border-indigo-300 dark:border-indigo-700" : "border-slate-200 dark:border-slate-700"}`} key={job.id}>
            <input className="mt-1 h-4 w-4 accent-indigo-600" checked={selected.has(job.id)} onChange={() => toggle(job.id)} type="checkbox" />
            <span className="min-w-0 flex-1"><span className="flex flex-wrap items-center gap-2 text-sm font-semibold text-slate-800 dark:text-slate-100"><span className="truncate">{job.title}</span>{job.match_score !== null && <span className={`rounded-full px-2 py-0.5 text-[11px] ${lowMatch ? "bg-amber-50 text-amber-700 dark:bg-amber-950/40 dark:text-amber-300" : "bg-emerald-50 text-emerald-700 dark:bg-emerald-950/40 dark:text-emerald-300"}`}>匹配 {Math.round(job.match_score)} 分</span>}</span><span className="mt-1 block text-xs text-slate-500 dark:text-slate-400">{job.company ?? "公司未注明"} · {job.location ?? "地点未注明"} · {job.salary_text}</span>{(lowMatch || expired || (job.warnings?.length ?? 0) > 0) && <span className="mt-1 block text-xs leading-5 text-amber-700 dark:text-amber-300">{expired ? "信息可能已过期，不能自动投递" : job.warnings?.[0] ?? "与当前简历匹配度不高，建议人工确认"}</span>}</span>
            {job.source_url && <a className="self-start text-xs font-medium text-indigo-600 hover:text-indigo-800 dark:text-indigo-300" href={job.source_url} onClick={(event) => { event.preventDefault(); event.stopPropagation(); window.open(job.source_url ?? "", "_blank", "noopener,noreferrer"); }} rel="noreferrer" target="_blank">原页</a>}
          </label>;
        })}
      </div>
      <div className="mt-4 flex flex-wrap items-center justify-between gap-2"><span className="text-xs text-slate-500 dark:text-slate-400">低匹配岗位默认未选，可手动勾选。</span><button className="rounded-xl bg-indigo-600 px-4 py-2.5 text-xs font-semibold text-white transition hover:bg-indigo-700 disabled:cursor-not-allowed disabled:opacity-50" disabled={selected.size === 0 || submitting} onClick={() => void prepare()} type="button">{submitting ? "准备中…" : `准备投递 ${selected.size} 个岗位`}</button></div>
    </section>
  );
}

function ApplicationConfirmationCard({
  action,
  sessionId,
  messageId,
  resumeId,
  onUpdate,
  onError,
}: {
  action: CareerAdvisorUiAction;
  sessionId: string;
  messageId: string;
  resumeId: string | null;
  onUpdate: (action: CareerAdvisorUiAction) => void;
  onError: (message: string) => void;
}) {
  const jobs = action.jobs ?? [];
  const [selected, setSelected] = useState<Set<string>>(() => new Set(action.job_ids ?? jobs.map((job) => job.id)));
  const [submitting, setSubmitting] = useState(false);
  const [cancelling, setCancelling] = useState(false);
  async function confirm() {
    if (!action.campaign_id || !action.confirmation_token || !selected.size || submitting) return;
    setSubmitting(true);
    try {
      let currentAction = action;
      const original = new Set(action.job_ids ?? []);
      if (selected.size !== original.size || [...selected].some((id) => !original.has(id))) {
        const prepared = await prepareCareerAdvisorApplication(sessionId, { message_id: messageId, job_ids: [...selected], resume_id: resumeId, plan_name: action.plan_name });
        currentAction = prepared.ui_action;
      }
      const result = await confirmCareerAdvisorApplication(sessionId, { message_id: messageId, campaign_id: currentAction.campaign_id ?? "", confirmation_token: currentAction.confirmation_token ?? "" });
      onUpdate(result.ui_action);
    } catch (reason) {
      onError(reason instanceof Error ? reason.message : "无法开始投递");
    } finally {
      setSubmitting(false);
    }
  }
  async function cancelDraft() {
    if (!action.campaign_id || cancelling) return;
    setCancelling(true);
    try {
      const result = await cancelCareerAdvisorApplication(sessionId, {
        message_id: messageId,
        campaign_id: action.campaign_id,
      });
      onUpdate(result.ui_action);
    } catch (reason) {
      onError(reason instanceof Error ? reason.message : "取消投递确认失败");
    } finally {
      setCancelling(false);
    }
  }
  return <section className="mt-4 rounded-2xl border border-amber-200 bg-amber-50/70 p-4 dark:border-amber-900/70 dark:bg-amber-950/25" aria-label="投递确认">
    <div className="flex flex-wrap items-start justify-between gap-3"><div><h3 className="text-sm font-semibold text-slate-900 dark:text-slate-100">确认投递岗位</h3><p className="mt-1 text-xs leading-5 text-slate-600 dark:text-slate-300">计划：{action.plan_name ?? "职业顾问投递计划"} · 使用当前简历</p></div><span className="rounded-full bg-white px-2.5 py-1 text-xs font-semibold text-amber-700 dark:bg-slate-900 dark:text-amber-300">二次确认</span></div>
    <div className="mt-3 space-y-2">{jobs.map((job) => <label className="flex cursor-pointer gap-3 rounded-xl border border-amber-100 bg-white p-3 dark:border-amber-900/50 dark:bg-slate-900" key={job.id}><input className="mt-1 h-4 w-4 accent-indigo-600" checked={selected.has(job.id)} onChange={() => setSelected((current) => { const next = new Set(current); if (next.has(job.id)) next.delete(job.id); else next.add(job.id); return next; })} type="checkbox" /><span className="min-w-0 flex-1"><span className="block text-sm font-semibold text-slate-800 dark:text-slate-100">{job.title}</span><span className="mt-1 block text-xs text-slate-500 dark:text-slate-400">{job.company ?? "公司未注明"} · {job.location ?? "地点未注明"} · {job.salary_text}</span><span className="mt-1 block text-xs text-slate-500 dark:text-slate-400">{typeof job.match_score === "number" ? `匹配 ${Math.round(job.match_score)} 分` : "匹配分待补充"} · {job.match_reason ?? "已通过状态校验"}</span></span></label>)}</div>
    {Array.isArray(action.warnings) && action.warnings.length > 0 && <div className="mt-3 rounded-xl border border-amber-200 bg-white/70 p-3 text-xs leading-5 text-amber-800 dark:border-amber-900/60 dark:bg-slate-900/60 dark:text-amber-200">{action.warnings.map((warning) => <p key={warning}>· {warning}</p>)}</div>}
    <div className="mt-4 flex flex-wrap justify-end gap-2"><button className="rounded-xl border border-slate-300 px-3 py-2.5 text-xs font-medium text-slate-600 hover:bg-white dark:border-slate-700 dark:text-slate-300 dark:hover:bg-slate-800" disabled={cancelling} onClick={() => void cancelDraft()} type="button">{cancelling ? "取消中…" : "取消"}</button><button className="rounded-xl bg-indigo-600 px-4 py-2.5 text-xs font-semibold text-white transition hover:bg-indigo-700 disabled:cursor-not-allowed disabled:opacity-50" disabled={!selected.size || submitting} onClick={() => void confirm()} type="button">{submitting ? "启动中…" : `确认并开始投递 ${selected.size} 个岗位`}</button></div>
  </section>;
}

function ApplicationProgressCard({
  action,
  sessionId,
  messageId,
  onUpdate,
  onError,
}: {
  action: CareerAdvisorUiAction;
  sessionId: string;
  messageId: string;
  onUpdate: (action: CareerAdvisorUiAction) => void;
  onError: (message: string) => void;
}) {
  const [refreshing, setRefreshing] = useState(false);
  const refresh = useCallback(async () => {
    if (!action.campaign_id || refreshing) return;
    setRefreshing(true);
    try {
      const result = await getCareerAdvisorApplicationProgress(sessionId, { message_id: messageId, campaign_id: action.campaign_id });
      onUpdate(result.ui_action);
    } catch (reason) {
      onError(reason instanceof Error ? reason.message : "无法获取投递进度");
    } finally {
      setRefreshing(false);
    }
  }, [action.campaign_id, messageId, onError, onUpdate, refreshing, sessionId]);
  async function cancel() {
    if (!action.campaign_id || refreshing) return;
    setRefreshing(true);
    try {
      const result = await cancelCareerAdvisorApplication(sessionId, { message_id: messageId, campaign_id: action.campaign_id });
      onUpdate(result.ui_action);
    } catch (reason) {
      onError(reason instanceof Error ? reason.message : "无法停止投递");
    } finally {
      setRefreshing(false);
    }
  }
  useEffect(() => {
    if (!action.campaign_id || ["cancelled", "completed", "failed"].includes(String(action.status))) return;
    const timer = window.setInterval(() => void refresh(), 3000);
    return () => window.clearInterval(timer);
  }, [action.campaign_id, action.status, refresh]);
  const items = Array.isArray(action.items) ? action.items : [];
  const progressStatus = String(action.status ?? "running");
  const progressTitle = progressStatus === "completed"
    ? "投递已完成"
    : progressStatus === "cancelled"
      ? "投递已取消"
      : progressStatus === "waiting_for_user"
        ? "等待人工处理"
        : "投递计划执行中";
  const terminalProgress = ["cancelled", "completed"].includes(progressStatus);
  return <section className="mt-4 rounded-2xl border border-emerald-200 bg-emerald-50/60 p-4 dark:border-emerald-900/70 dark:bg-emerald-950/25" aria-label="投递进度"><div className="flex flex-wrap items-start justify-between gap-3"><div><h3 className="text-sm font-semibold text-slate-900 dark:text-slate-100">{progressTitle}</h3><p className="mt-1 text-xs text-slate-600 dark:text-slate-300">已提交 {action.submitted_count ?? 0} · 需手动 {action.manual_count ?? 0} · 等待处理 {action.waiting_count ?? 0}</p></div><div className="flex gap-2"><button className="rounded-lg border border-emerald-300 px-3 py-2 text-xs font-medium text-emerald-700 hover:bg-white dark:border-emerald-800 dark:text-emerald-300 dark:hover:bg-slate-800" disabled={refreshing} onClick={() => void refresh()} type="button">刷新</button><button className="rounded-lg border border-rose-200 px-3 py-2 text-xs font-medium text-rose-600 hover:bg-rose-50 dark:border-rose-900 dark:text-rose-300 dark:hover:bg-slate-800" disabled={refreshing || terminalProgress} onClick={() => void cancel()} type="button">停止投递</button></div></div><div className="mt-3 space-y-2">{items.map((item) => { const row = item as Record<string, unknown>; const status = metadataText(row.application_status, metadataText(row.task_status, "处理中")); const terminal = status === "SUBMITTED" ? "text-emerald-700 dark:text-emerald-300" : status === "MANUAL_REQUIRED" ? "text-amber-700 dark:text-amber-300" : status.includes("FAILED") || status.includes("RISK") ? "text-rose-700 dark:text-rose-300" : "text-slate-600 dark:text-slate-300"; return <div className="flex items-center justify-between gap-3 rounded-xl border border-emerald-100 bg-white p-3 text-xs dark:border-emerald-900/50 dark:bg-slate-900" key={String(row.task_id)}><span className="min-w-0 truncate font-medium text-slate-700 dark:text-slate-200">{metadataText(row.job_title, "岗位")}</span><span className={terminal}>{status}</span></div>; })}</div></section>;
}

function CareerAdvisorActionCard({
  action,
  sessionId,
  messageId,
  resumeId,
  onUpdate,
  onError,
}: {
  action: CareerAdvisorUiAction;
  sessionId: string;
  messageId: string;
  resumeId: string | null;
  onUpdate: (action: CareerAdvisorUiAction) => void;
  onError: (message: string) => void;
}) {
  if (action.type === "job_search_results") return <JobSearchActionCard action={action} sessionId={sessionId} messageId={messageId} resumeId={resumeId} onUpdate={onUpdate} onError={onError} />;
  if (action.type === "application_confirmation") return <ApplicationConfirmationCard action={action} sessionId={sessionId} messageId={messageId} resumeId={resumeId} onUpdate={onUpdate} onError={onError} />;
  if (action.type === "application_progress") return <ApplicationProgressCard action={action} sessionId={sessionId} messageId={messageId} onUpdate={onUpdate} onError={onError} />;
  return null;
}

function MessageCard({
  message,
  sessionId,
  resumeId,
  onRegenerate,
  onCopy,
  onToggleExpanded,
  copied,
  expanded,
  regenerating,
  onEvidence,
  onActionUpdate,
  onError,
}: {
  message: CareerAdvisorMessage;
  sessionId: string;
  resumeId: string | null;
  onRegenerate: (message: CareerAdvisorMessage) => void;
  onCopy: (message: CareerAdvisorMessage) => void;
  onToggleExpanded: (messageId: string) => void;
  copied: boolean;
  expanded: boolean;
  regenerating: boolean;
  onEvidence: (message: CareerAdvisorMessage) => void;
  onActionUpdate: (messageId: string, action: CareerAdvisorUiAction) => void;
  onError: (message: string) => void;
}) {
  const isUser = message.role === "user";
  if (isUser) {
    return (
      <div className="flex justify-end">
        <div className="advisor-user-message max-w-[85%] whitespace-pre-wrap rounded-3xl px-5 py-3 text-[15px] leading-7">
          {message.content}
        </div>
      </div>
    );
  }
  const sampleCount = metadataNumber(message.answer_metadata.sample_count);
  const factSource = metadataText(message.answer_metadata.fact_source);
  const adviceSource = metadataText(message.answer_metadata.advice_source);
  const displayContent = presentationMarkdown(message.content);
  const presentation = message.status === "COMPLETED" ? splitAdvisorAnswer(displayContent) : { answer: displayContent, evidence: "" };
  const canCollapse = message.status === "COMPLETED" && displayContent.length > 900;
  const uiAction = messageUiAction(message);
  return (
    <article className="advisor-answer py-4">
      <div className="flex flex-wrap items-center gap-2 text-xs text-slate-500">
        {message.status !== "COMPLETED" && <span className={`rounded-full px-2 py-1 font-medium ${statusClass(message.status)}`}>
          {statusLabels[message.status] ?? message.status}
        </span>}
        {message.intent && <span>{intentLabels[message.intent] ?? message.intent}</span>}
        {sampleCount > 0 && <span>· {sampleCount} 个岗位样本</span>}
        {factSource && <span>· {factSource === "database" ? "来自岗位知识库" : "无检索数据"}</span>}
        {adviceSource && <span>· {adviceSource === "llm" ? "AI 整理" : "规则整理"}</span>}
      </div>
      {displayContent ? (
        <div className="relative">
          <div className={canCollapse && !expanded ? "max-h-[28rem] overflow-hidden" : ""}>
            <MarkdownContent className="mt-3" value={presentation.answer} />
          </div>
          {canCollapse && !expanded && <div className="pointer-events-none absolute inset-x-0 bottom-0 h-24 bg-gradient-to-t from-slate-50 to-transparent dark:from-slate-800" />}
        </div>
      ) : (
        <div className="advisor-thinking mt-4 flex items-center gap-3 rounded-xl px-3 py-3 text-sm text-slate-500">
          <span className="relative flex h-3 w-3"><span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-indigo-400 opacity-40" /><span className="relative inline-flex h-3 w-3 rounded-full bg-indigo-500" /></span>
          <span>正在理解目标并检索岗位知识库…</span>
        </div>
      )}
      {message.error_message && <p className="mt-3 text-sm text-rose-600">{message.error_message}</p>}
      {presentation.evidence && <details className="mt-4 rounded-xl border border-slate-200 p-3"><summary className="cursor-pointer text-xs text-slate-500">数据分析与 JD 摘录（辅助依据）</summary><MarkdownContent value={presentation.evidence} className="mt-3" /></details>}
      {uiAction && <CareerAdvisorActionCard action={uiAction} sessionId={sessionId} messageId={message.id} resumeId={resumeId} onUpdate={(action) => onActionUpdate(message.id, action)} onError={onError} />}
      {message.status !== "RUNNING" && <button className="mt-3 rounded-full border border-slate-200 px-3 py-1.5 text-xs text-indigo-600" onClick={() => onEvidence(message)} type="button">参考岗位 · {message.citations.length} 条依据</button>}
      {message.status === "COMPLETED" && !message.id.startsWith("local-") && (
        <div className="mt-4 flex flex-wrap gap-x-4 gap-y-2 border-t border-slate-200 pt-3">
          {canCollapse && <button className="text-xs font-semibold text-indigo-600 transition hover:text-indigo-800" onClick={() => onToggleExpanded(message.id)} type="button">{expanded ? "收起回答" : "展开完整回答"}</button>}
          <button className="text-xs font-medium text-slate-500 transition hover:text-indigo-700" onClick={() => onCopy(message)} type="button">{copied ? "已复制" : "复制回答"}</button>
        <button
          className="text-xs font-medium text-slate-500 transition hover:text-indigo-700 disabled:opacity-50"
          disabled={regenerating}
          onClick={() => onRegenerate(message)}
          type="button"
        >
          {regenerating ? "重新生成中…" : "重新生成"}
        </button>
        </div>
      )}
    </article>
  );
}

export default function CareerAdvisorPage() {
  const [sessions, setSessions] = useState<CareerAdvisorSession[]>([]);
  const [sessionTotal, setSessionTotal] = useState(0);
  const [loadingMoreSessions, setLoadingMoreSessions] = useState(false);
  const [selectedSession, setSelectedSession] = useState<CareerAdvisorSession | null>(null);
  const [resumes, setResumes] = useState<Resume[]>([]);
  const [selectedResumeId, setSelectedResumeId] = useState<string | null>(null);
  const [filters, setFilters] = useState<JobKnowledgeFilters>(emptyFilters);
  const [input, setInput] = useState("");
  const [focusMode, setFocusMode] = useState(false);
  const [evidenceMessage, setEvidenceMessage] = useState<CareerAdvisorMessage | null>(null);
  const [awayFromBottom, setAwayFromBottom] = useState(false);
  const followMessages = useRef(true);
  const previousSessionId = useRef<string | null>(null);
  const [generationStage, setGenerationStage] = useState("idle");
  const [generationStatusLabel, setGenerationStatusLabel] = useState("");
  const [retrievedSampleCount, setRetrievedSampleCount] = useState(0);
  const [knowledgeRun, setKnowledgeRun] = useState<KnowledgeHealth["latest_run"]>(null);
  const [knowledgeHealth, setKnowledgeHealth] = useState<KnowledgeHealth | null>(null);
  const [startingKnowledge, setStartingKnowledge] = useState(false);
  const [loading, setLoading] = useState(true);
  const [loadingSession, setLoadingSession] = useState(false);
  const [loadingOlderMessages, setLoadingOlderMessages] = useState(false);
  const [savingContext, setSavingContext] = useState(false);
  const [generating, setGenerating] = useState(false);
  const [stopping, setStopping] = useState(false);
  const [regeneratingId, setRegeneratingId] = useState<string | null>(null);
  const [copiedMessageId, setCopiedMessageId] = useState<string | null>(null);
  const [renameOpen, setRenameOpen] = useState(false);
  const [renameInput, setRenameInput] = useState("");
  const [deleteOpen, setDeleteOpen] = useState(false);
  const [filtersOpen, setFiltersOpen] = useState(false);
  const [mobileSessionsOpen, setMobileSessionsOpen] = useState(false);
  const [sessionMenuOpen, setSessionMenuOpen] = useState(false);
  const [collapsedMessages, setCollapsedMessages] = useState<Set<string>>(() => new Set());
  const [activeMessageId, setActiveMessageId] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const streamAbortRef = useRef<AbortController | null>(null);
  const sendingRef = useRef(false);
  const messagesEndRef = useRef<HTMLDivElement | null>(null);
  const messagesViewportRef = useRef<HTMLDivElement | null>(null);
  const inputRef = useRef<HTMLTextAreaElement | null>(null);
  const knowledgeRunId = knowledgeRun?.id;
  const knowledgeRunStatus = knowledgeRun?.status;
  const messageCount = selectedSession?.messages.length ?? 0;
  const lastMessageContent = messageCount > 0 ? selectedSession?.messages[messageCount - 1]?.content ?? "" : "";

  function syncSessionContext(session: CareerAdvisorSession) {
    setFilters(cloneFilters(session.context_filters ?? emptyFilters()));
    setSelectedResumeId(session.resume_id);
  }

  function upsertSession(session: CareerAdvisorSession) {
    setSessions((current) => [session, ...current.filter((item) => item.id !== session.id)]);
  }

  async function loadSession(id: string, showLoading = true) {
    if (showLoading) setLoadingSession(true);
    try {
      const session = await getCareerAdvisorSession(id);
      setSelectedSession(session);
      syncSessionContext(session);
      upsertSession(session);
      return session;
    } finally {
      if (showLoading) setLoadingSession(false);
    }
  }

  useEffect(() => {
    let disposed = false;
    Promise.all([getCareerAdvisorSessions(), getResumes(), getKnowledgeHealth()])
      .then(([sessionResponse, resumeResponse, knowledgeResponse]) => {
        if (disposed) return;
        setSessions(sessionResponse.items);
        setSessionTotal(sessionResponse.total);
        setResumes(resumeResponse.items);
        setKnowledgeHealth(knowledgeResponse);
        setKnowledgeRun(knowledgeResponse.latest_run);
        const defaultResume = resumeResponse.items.find((resume) => resume.is_default) ?? resumeResponse.items[0] ?? null;
        setSelectedResumeId(defaultResume?.id ?? null);
        const firstSession = sessionResponse.items[0] ?? null;
        if (firstSession) {
          getCareerAdvisorSession(firstSession.id)
            .then((session) => {
              if (disposed) return;
              setSelectedSession(session);
              syncSessionContext(session);
              upsertSession(session);
            })
            .catch((reason) => {
              if (!disposed) setError(reason instanceof Error ? reason.message : "无法加载最近会话");
            });
        }
      })
      .catch((reason) => setError(reason instanceof Error ? reason.message : "无法加载职业顾问数据"))
      .finally(() => setLoading(false));
    return () => { disposed = true; };
  }, []);

  useEffect(() => {
    if (!knowledgeRunId || !knowledgeRunStatus || ["SUCCEEDED", "FAILED", "CANCELLED"].includes(knowledgeRunStatus)) return;
    let current = true;
    let pending = false;
    const timer = window.setInterval(() => {
      if (pending) return;
      pending = true;
      getKnowledgeHealth()
        .then((response) => { if (current) { setKnowledgeHealth(response); setKnowledgeRun(response.latest_run); } })
        .catch((reason) => { if (current) setError(reason instanceof Error ? reason.message : "无法刷新知识库进度"); })
        .finally(() => { pending = false; });
    }, 3000);
    return () => { current = false; window.clearInterval(timer); };
  }, [knowledgeRunId, knowledgeRunStatus]);

  useEffect(() => {
    const viewport = messagesViewportRef.current;
    if (!viewport) return;
    if (followMessages.current) viewport.scrollTop = viewport.scrollHeight;
  }, [generating, messageCount, lastMessageContent, loadingSession]);

  useEffect(() => {
    const id = selectedSession?.id ?? null;
    if (previousSessionId.current === id) return;
    previousSessionId.current = id;
    followMessages.current = true;
    setAwayFromBottom(false);
    setEvidenceMessage(null);
    const viewport = messagesViewportRef.current;
    if (viewport) viewport.scrollTop = viewport.scrollHeight;
    try { setInput(localStorage.getItem(`careerpilot:advisor-draft:${id ?? "new"}`) || ""); } catch { setInput(""); }
  }, [selectedSession?.id]);

  useEffect(() => {
    if (!inputRef.current) return;
    inputRef.current.style.height = "auto";
    inputRef.current.style.height = `${Math.min(inputRef.current.scrollHeight, 180)}px`;
  }, [input]);

  function updateDraft(value: string) {
    setInput(value);
    try { localStorage.setItem(`careerpilot:advisor-draft:${selectedSession?.id ?? "new"}`, value); } catch { /* Storage is optional. */ }
  }

  function toggleMessageExpanded(messageId: string) {
    setCollapsedMessages((current) => {
      const next = new Set(current);
      if (next.has(messageId)) next.delete(messageId);
      else next.add(messageId);
      return next;
    });
  }

  function applyPrompt(prompt: string) {
    updateDraft(prompt);
    window.requestAnimationFrame(() => inputRef.current?.focus());
  }

  async function handleNewSession() {
    if (generating) return;
    setError(null);
    try {
      const session = await createCareerAdvisorSession({
        resume_id: selectedResumeId,
        context_filters: filters,
      });
      setSelectedSession(session);
      syncSessionContext(session);
      upsertSession(session);
      setSessionTotal((current) => current + 1);
      setFiltersOpen(false);
      setMobileSessionsOpen(false);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "无法创建会话");
    }
  }

  function openRename() {
    if (!selectedSession) return;
    setRenameInput(selectedSession.title);
    setRenameOpen(true);
  }

  async function confirmRename() {
    if (!selectedSession) return;
    const title = renameInput.trim();
    if (!title || title === selectedSession.title) {
      setRenameOpen(false);
      return;
    }
    try {
      const updated = await updateCareerAdvisorSession(selectedSession.id, { title });
      setSelectedSession(updated);
      upsertSession(updated);
      setRenameOpen(false);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "会话重命名失败");
    }
  }

  function openDelete() {
    if (selectedSession) setDeleteOpen(true);
  }

  async function confirmDelete() {
    if (!selectedSession) return;
    setError(null);
    try {
      await deleteCareerAdvisorSession(selectedSession.id);
      setDeleteOpen(false);
      const remaining = sessions.filter((item) => item.id !== selectedSession.id);
      setSessions(remaining);
      setSessionTotal((current) => Math.max(0, current - 1));
      const next = remaining[0] ?? null;
      setSelectedSession(next);
      if (next) await loadSession(next.id, false);
      else {
        setFilters(emptyFilters());
        setSelectedResumeId(resumes.find((resume) => resume.is_default)?.id ?? resumes[0]?.id ?? null);
      }
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "会话删除失败");
    }
  }

  async function handleSelectSession(id: string) {
    if (generating || loadingSession) return;
    setError(null);
    setMobileSessionsOpen(false);
    setCollapsedMessages(new Set());
    try {
      await loadSession(id);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "无法加载会话");
    }
  }

  async function handleLoadMoreSessions() {
    if (loadingMoreSessions || sessions.length >= sessionTotal) return;
    setLoadingMoreSessions(true);
    try {
      const response = await getCareerAdvisorSessions({ limit: 30, offset: sessions.length });
      setSessionTotal(response.total);
      setSessions((current) => {
        const known = new Set(current.map((item) => item.id));
        return [...current, ...response.items.filter((item) => !known.has(item.id))];
      });
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "无法加载更多会话");
    } finally {
      setLoadingMoreSessions(false);
    }
  }

  async function handleLoadOlderMessages() {
    if (!selectedSession || !selectedSession.message_has_more || loadingOlderMessages) return;
    setLoadingOlderMessages(true);
    try {
      const offset = selectedSession.messages.length;
      const older = await getCareerAdvisorSession(selectedSession.id, { limit: 50, offset });
      const viewport = messagesViewportRef.current;
      const previousHeight = viewport?.scrollHeight ?? 0;
      const previousTop = viewport?.scrollTop ?? 0;
      followMessages.current = false;
      const merged = {
        ...selectedSession,
        messages: [...older.messages, ...selectedSession.messages],
        message_total: older.message_total,
        message_offset: 0,
        message_has_more: older.message_has_more,
      };
      setSelectedSession(merged);
      upsertSession(merged);
      window.requestAnimationFrame(() => { if (viewport) viewport.scrollTop = previousTop + viewport.scrollHeight - previousHeight; });
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "无法加载更早消息");
    } finally {
      setLoadingOlderMessages(false);
    }
  }

  async function handleStartKnowledgeIndex(mode: "incremental" | "backfill") {
    if (startingKnowledge || (knowledgeRun && ["PENDING", "RUNNING"].includes(knowledgeRun.status))) return;
    setStartingKnowledge(true);
    setError(null);
    try {
      const run = await createKnowledgeIndexRun({ mode, auto_start: true });
      setKnowledgeRun(run);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "无法启动知识库回填");
    } finally {
      setStartingKnowledge(false);
    }
  }

  function handleStartBackfill() {
    return handleStartKnowledgeIndex("backfill");
  }

  function handleStartIncremental() {
    return handleStartKnowledgeIndex("incremental");
  }

  async function handleSaveContext() {
    if (!selectedSession) return;
    setSavingContext(true);
    setError(null);
    try {
      const updated = await updateCareerAdvisorSession(selectedSession.id, {
        resume_id: selectedResumeId,
        context_filters: filters,
      });
      setSelectedSession(updated);
      syncSessionContext(updated);
      upsertSession(updated);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "筛选条件保存失败");
    } finally {
      setSavingContext(false);
    }
  }

  function updateFilter<Key extends keyof JobKnowledgeFilters>(key: Key, value: JobKnowledgeFilters[Key]) {
    setFilters((current) => ({ ...current, [key]: value }));
  }

  function toggleJobType(jobType: string) {
    setFilters((current) => ({
      ...current,
      job_types: current.job_types.includes(jobType)
        ? current.job_types.filter((item) => item !== jobType)
        : [...current.job_types, jobType],
    }));
  }

  function applyStreamEvent(
    sessionId: string,
    eventType: string,
    payload: Record<string, unknown>,
  ) {
    if (eventType === "message_started") {
      const messageId = metadataText(payload.message_id);
      if (!messageId) return;
      setActiveMessageId(messageId);
      setGenerationStage("understanding");
      setGenerationStatusLabel("正在理解你的目标");
      setRetrievedSampleCount(0);
      setSelectedSession((current) => current && current.id === sessionId
        ? { ...current, messages: [...current.messages, emptyAssistantMessage(sessionId, messageId)] }
        : current);
    } else if (eventType === "ui_action_created") {
      const messageId = metadataText(payload.message_id);
      const action = payload.ui_action;
      if (!messageId || !action || typeof action !== "object") return;
      setSelectedSession((current) => current && current.id === sessionId
        ? { ...current, messages: current.messages.map((message) => message.id === messageId ? { ...message, answer_metadata: { ...message.answer_metadata, ui_action: action } } : message) }
        : current);
    } else if (eventType === "stage_changed") {
      setGenerationStage(metadataText(payload.stage, "understanding"));
      setGenerationStatusLabel(metadataText(payload.label));
    } else if (eventType === "retrieval_status") {
      const stage = metadataText(payload.stage);
      setGenerationStage(stage === "query_analysis" || stage === "retrieval_planning" ? "understanding" : "searching");
      setGenerationStatusLabel(metadataText(payload.label, "正在检索岗位知识库"));
    } else if (eventType === "evidence_status") {
      setGenerationStage("analyzing");
      setGenerationStatusLabel(metadataText(payload.label, "正在评估岗位证据"));
    } else if (eventType === "intent_detected") {
      const intent = metadataText(payload.intent) as CareerAdvisorIntent;
      setSelectedSession((current) => current && current.id === sessionId
        ? { ...current, messages: current.messages.map((message) => message.id === metadataText(payload.message_id) || (message.role === "assistant" && message.status === "RUNNING") ? { ...message, intent } : message) }
        : current);
    } else if (eventType === "facts_ready") {
      setRetrievedSampleCount(metadataNumber(payload.sample_count));
      setGenerationStatusLabel("已整理岗位事实，正在生成建议");
    } else if (eventType === "delta") {
      const delta = metadataText(payload.content);
      const messageId = metadataText(payload.message_id);
      setSelectedSession((current) => current && current.id === sessionId
        ? { ...current, messages: current.messages.map((message) => message.id === messageId ? { ...message, content: `${message.content}${delta}` } : message) }
        : current);
    } else if (eventType === "message_failed") {
      const messageId = metadataText(payload.message_id);
      setError(metadataText(payload.error, "职业顾问生成失败"));
      setSelectedSession((current) => current && current.id === sessionId
        ? { ...current, messages: current.messages.map((message) => message.id === messageId ? { ...message, status: "FAILED", error_message: metadataText(payload.error) } : message) }
        : current);
    } else if (eventType === "message_cancelled") {
      setSelectedSession((current) => current && current.id === sessionId
        ? { ...current, messages: current.messages.map((message) => message.id === metadataText(payload.message_id) ? { ...message, status: "CANCELLED" } : message) }
        : current);
    } else if (eventType === "message_state") {
      const message = payload as unknown as CareerAdvisorMessage;
      setActiveMessageId(null);
      setGenerationStatusLabel("");
      setSelectedSession((current) => current && current.id === sessionId
        ? { ...current, messages: current.messages.map((item) => item.id === message.id ? message : item) }
        : current);
    }
  }

  function handleActionUpdate(messageId: string, action: CareerAdvisorUiAction) {
    setSelectedSession((current) => current ? {
      ...current,
      messages: current.messages.map((message) => message.id === messageId
        ? { ...message, ui_action: action, answer_metadata: { ...message.answer_metadata, ui_action: action } }
        : message),
    } : current);
  }

  async function handleSend(event?: FormEvent<HTMLFormElement>) {
    event?.preventDefault();
    const content = input.trim();
    if (!content || generating || sendingRef.current || loadingSession) return;
    sendingRef.current = true;
    setGenerating(true);
    setError(null);
    let session = selectedSession;
    try {
      if (!session) {
        session = await createCareerAdvisorSession({ resume_id: selectedResumeId, context_filters: filters });
        setSelectedSession(session);
        upsertSession(session);
        setSessionTotal((current) => current + 1);
      }
      const sessionId = session.id;
      const controller = new AbortController();
      streamAbortRef.current = controller;
      setGenerating(true);
      setStopping(false);
      setGenerationStage("understanding");
      setRetrievedSampleCount(0);
      updateDraft("");
      followMessages.current = true;
      setAwayFromBottom(false);
      setSelectedSession((current) => current && current.id === sessionId
        ? { ...current, messages: [...current.messages, localUserMessage(sessionId, content)] }
        : current);

      await streamCareerAdvisorMessage(
        sessionId,
        { content, resume_id: selectedResumeId, filters },
        (eventType, payload) => applyStreamEvent(sessionId, eventType, payload),
        controller.signal,
      );
      await loadSession(sessionId, false);
    } catch (reason) {
      if (!(reason instanceof DOMException && reason.name === "AbortError")) {
        setError(reason instanceof Error ? reason.message : "职业顾问生成失败");
      }
    } finally {
      sendingRef.current = false;
      streamAbortRef.current = null;
      setGenerating(false);
      setStopping(false);
      setActiveMessageId(null);
      setGenerationStage("idle");
    }
  }

  async function handleStop() {
    const messageId = activeMessageId;
    const controller = streamAbortRef.current;
    if (!messageId) {
      controller?.abort();
      return;
    }
    setStopping(true);
    try {
      await cancelCareerAdvisorMessage(messageId);
      controller?.abort();
      if (selectedSession) await loadSession(selectedSession.id, false);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "停止生成失败");
    } finally {
      setStopping(false);
    }
  }

  async function handleRegenerate(message: CareerAdvisorMessage) {
    const session = selectedSession;
    if (!session || generating) return;
    const messageIndex = session.messages.findIndex((item) => item.id === message.id);
    const previousUser = [...session.messages.slice(0, messageIndex)].reverse().find((item) => item.role === "user");
    if (!previousUser) {
      setError("没有可重新生成的用户问题");
      return;
    }
    const sessionId = session.id;
    const controller = new AbortController();
    setRegeneratingId(message.id);
    streamAbortRef.current = controller;
    setGenerating(true);
    setStopping(false);
    setGenerationStage("understanding");
    setRetrievedSampleCount(0);
    setError(null);
    try {
      setSelectedSession((current) => current && current.id === sessionId
        ? { ...current, messages: [...current.messages, localUserMessage(sessionId, previousUser.content)] }
        : current);
      await streamRegenerateCareerAdvisorMessage(
        message.id,
        (eventType, payload) => applyStreamEvent(sessionId, eventType, payload),
        controller.signal,
      );
      await loadSession(sessionId, false);
    } catch (reason) {
      if (!(reason instanceof DOMException && reason.name === "AbortError")) {
        setError(reason instanceof Error ? reason.message : "重新生成失败");
      }
    } finally {
      streamAbortRef.current = null;
      setGenerating(false);
      setStopping(false);
      setActiveMessageId(null);
      setGenerationStage("idle");
      setRegeneratingId(null);
    }
  }

  async function handleCopy(message: CareerAdvisorMessage) {
    try {
      await navigator.clipboard.writeText(presentationMarkdown(message.content));
      setCopiedMessageId(message.id);
      window.setTimeout(() => setCopiedMessageId((current) => current === message.id ? null : current), 1800);
    } catch {
      setError("复制失败，请检查浏览器剪贴板权限");
    }
  }

  const messages = selectedSession?.messages ?? [];
  const latestAssistantMessage = [...messages].reverse().find((message) => message.role === "assistant" && message.status !== "RUNNING") ?? null;
  const activeFilterCount = filterCount(filters);
  const selectedResumeName = resumes.find((resume) => resume.id === selectedResumeId)?.name ?? "未关联";
  const suggestedFollowUps = followUpPrompts(latestAssistantMessage);
  const knowledgeStatus = knowledgeHealth?.status ?? (
    knowledgeHealth?.ready
      ? "ready"
      : knowledgeHealth && (knowledgeHealth.document_count === 0 || knowledgeHealth.chunk_count === 0)
        ? "not_built"
        : "needs_update"
  );

  return (
    <div className={`career-advisor-page advisor-workspace ${focusMode ? "advisor-focus" : ""}`}>
      <header className="advisor-toolbar">
        <div className="flex min-w-0 items-center gap-2 sm:gap-4">
          <button aria-label={focusMode ? "显示系统导航" : "进入专注聊天"} aria-pressed={!focusMode} className="advisor-toolbar-button" onClick={() => setFocusMode((value) => !value)} type="button">{focusMode ? "☰ 导航" : "专注"}</button>
          <button className="advisor-toolbar-button" disabled={generating} onClick={() => setMobileSessionsOpen(true)} type="button">咨询记录</button>
          <h1 className="hidden text-base font-semibold sm:block">职业顾问</h1>
        </div>
        <button disabled={generating || loadingSession} className="shrink-0 rounded-xl bg-indigo-600 px-4 py-2 text-sm font-semibold text-white disabled:opacity-50" onClick={handleNewSession} type="button">
          + 新建咨询
        </button>
      </header>

      {error && <div className="rounded-xl border border-rose-200 bg-rose-50 px-4 py-3 text-sm text-rose-700">{error}</div>}
      {loading && <div aria-label="正在加载岗位知识库状态" className="h-16 animate-pulse rounded-2xl border border-slate-200 bg-white" />}
      {knowledgeStatus === "ready" && knowledgeHealth && <p className="text-xs text-slate-500">知识库已覆盖 {knowledgeHealth.indexed_jobs}/{knowledgeHealth.jobs_total} 个岗位 · {knowledgeHealth.chunk_count} 个知识片段 · {knowledgeHealth.embedded_chunk_count ?? knowledgeHealth.chunk_count} 个向量{knowledgeHealth.updated_at ? ` · 更新于 ${new Date(knowledgeHealth.updated_at).toLocaleString("zh-CN")}` : ""}。是否足以回答当前问题，以回答中的检索证据为准。</p>}
      {!loading && knowledgeStatus === "not_built" && !["PENDING", "RUNNING", "FAILED"].includes(knowledgeRun?.status ?? "") && <div className="flex flex-col justify-between gap-3 rounded-2xl border border-amber-200 bg-amber-50 px-4 py-3 text-sm text-amber-800 sm:flex-row sm:items-center"><div><p className="font-semibold">岗位知识库尚未构建</p><p className="mt-1 text-xs leading-5">当前没有文档或知识片段，请先完成一次全量回填。</p></div><button className="shrink-0 rounded-lg bg-amber-600 px-3 py-2 text-xs font-semibold text-white transition hover:bg-amber-700 disabled:opacity-50" disabled={startingKnowledge} onClick={handleStartBackfill} type="button">{startingKnowledge ? "启动中…" : "开始全量回填"}</button></div>}
      {!loading && knowledgeHealth && ["partial", "needs_update"].includes(knowledgeStatus) && !["PENDING", "RUNNING", "FAILED"].includes(knowledgeRun?.status ?? "") && <div className="flex flex-col justify-between gap-3 rounded-2xl border border-amber-200 bg-amber-50 px-4 py-3 text-sm text-amber-800 sm:flex-row sm:items-center"><div><p className="font-semibold">{knowledgeStatus === "needs_update" ? "岗位知识库需要更新" : "岗位知识库部分可用"}</p><p className="mt-1 text-xs leading-5">已有 {knowledgeHealth.compatible_jobs ?? knowledgeHealth.indexed_jobs}/{knowledgeHealth.jobs_total} 个岗位可检索，{knowledgeHealth.needs_update_jobs ?? Math.max(0, knowledgeHealth.jobs_total - knowledgeHealth.indexed_jobs)} 个岗位需要更新 embedding 或知识块。</p></div><button className="shrink-0 rounded-lg bg-amber-600 px-3 py-2 text-xs font-semibold text-white transition hover:bg-amber-700 disabled:opacity-50" disabled={startingKnowledge} onClick={handleStartIncremental} type="button">{startingKnowledge ? "启动中…" : `增量更新 ${knowledgeHealth.needs_update_jobs ?? Math.max(0, knowledgeHealth.jobs_total - knowledgeHealth.indexed_jobs)} 个岗位`}</button></div>}
      {knowledgeRun && ["PENDING", "RUNNING"].includes(knowledgeRun.status) && <div className="rounded-2xl border border-indigo-200 bg-indigo-50 px-4 py-3 text-sm text-indigo-800"><div className="flex flex-wrap items-center justify-between gap-2"><span className="font-semibold">知识库正在增量更新，检索速度可能降低</span><span>{knowledgeRun.progress}% · {knowledgeRun.processed_jobs}/{knowledgeRun.total_jobs} 个岗位</span></div><div className="mt-2 h-2 overflow-hidden rounded-full bg-indigo-100"><div className="h-full rounded-full bg-indigo-600 transition-all" style={{ width: `${knowledgeRun.progress}%` }} /></div></div>}
      {knowledgeRun?.status === "FAILED" && <div className="flex flex-col justify-between gap-3 rounded-2xl border border-rose-200 bg-rose-50 px-4 py-3 text-sm text-rose-700 sm:flex-row sm:items-center"><div><p className="font-semibold">岗位知识库更新失败</p><p className="mt-1 text-xs leading-5">{knowledgeRun.error ?? "请重新启动索引任务。"}</p></div><button className="shrink-0 rounded-lg bg-rose-600 px-3 py-2 text-xs font-semibold text-white transition hover:bg-rose-700 disabled:opacity-50" disabled={startingKnowledge} onClick={knowledgeStatus === "not_built" ? handleStartBackfill : handleStartIncremental} type="button">{startingKnowledge ? "启动中…" : knowledgeStatus === "not_built" ? "重新全量回填" : `重试增量更新 ${knowledgeHealth?.needs_update_jobs ?? ""} 个岗位`}</button></div>}

      {mobileSessionsOpen && <AdvisorDialog title="咨询记录" onClose={() => setMobileSessionsOpen(false)}>
          <SessionList loading={loading} loadingMore={loadingMoreSessions} onLoadMore={() => void handleLoadMoreSessions()} onSelect={(id) => void handleSelectSession(id)} selectedSessionId={selectedSession?.id ?? null} sessionTotal={sessionTotal} sessions={sessions} />
      </AdvisorDialog>}

      <div className="advisor-chat-layout">
        <div className="advisor-chat-main">
          <section className="advisor-context">
            <div className="flex items-center justify-between gap-3 px-4 py-3">
              <div className="min-w-0">
                <h2 className="truncate text-sm font-medium text-slate-900">{selectedSession?.title ?? "开始一场职业咨询"}</h2>
                <div className="mt-2 flex flex-wrap gap-2 text-xs text-slate-500">
                  <span className="rounded-full bg-slate-100 px-2.5 py-1">简历：{selectedResumeName}</span>
                  <span className="rounded-full bg-slate-100 px-2.5 py-1">{activeFilterCount > 0 ? `${activeFilterCount} 组岗位条件` : "全部岗位数据"}</span>
                </div>
              </div>
              <div className="flex items-center gap-2">
                <button disabled={generating} aria-expanded={filtersOpen} className="shrink-0 rounded-xl border border-indigo-200 px-3 py-2 text-xs font-semibold text-indigo-700 transition hover:bg-indigo-50" onClick={() => setFiltersOpen((current) => !current)} type="button">{filtersOpen ? "收起条件" : "调整条件"}</button>
                {selectedSession && <div className="relative">
                  <button disabled={generating} aria-expanded={sessionMenuOpen} aria-label="更多会话操作" className="grid h-9 w-9 place-items-center rounded-xl border border-slate-200 text-lg leading-none text-slate-500 transition hover:border-indigo-300 hover:text-indigo-700" onClick={() => setSessionMenuOpen((current) => !current)} type="button">···</button>
                  {sessionMenuOpen && <div className="absolute right-0 top-11 z-20 w-32 animate-[advisorReveal_150ms_ease-out] rounded-xl border border-slate-200 bg-white p-1.5 shadow-lg">
                    <button className="w-full rounded-lg px-3 py-2 text-left text-xs text-slate-600 hover:bg-slate-50" onClick={() => { setSessionMenuOpen(false); openRename(); }} type="button">重命名</button>
                    <button className="w-full rounded-lg px-3 py-2 text-left text-xs text-rose-600 hover:bg-rose-50" onClick={() => { setSessionMenuOpen(false); openDelete(); }} type="button">删除会话</button>
                  </div>}
                </div>}
              </div>
            </div>
            {filtersOpen && <AdvisorDialog title="咨询条件" onClose={() => setFiltersOpen(false)}><div className="advisor-context-editor p-1">
              <div className="grid gap-4 md:grid-cols-2 2xl:grid-cols-3">
              <label className="text-xs font-medium text-slate-500">参考简历
                <select className="mt-2 w-full rounded-xl border border-slate-200 bg-white px-3 py-2.5 text-sm text-slate-800 outline-none transition focus:border-indigo-400" onChange={(event) => setSelectedResumeId(event.target.value || null)} value={selectedResumeId ?? ""}>
                  <option value="">不关联简历</option>
                  {resumes.map((resume) => <option key={resume.id} value={resume.id}>{resume.name}{resume.is_default ? "（默认）" : ""}</option>)}
                </select>
              </label>
              <label className="text-xs font-medium text-slate-500">城市（逗号分隔）
                <input className="mt-2 w-full rounded-xl border border-slate-200 bg-white px-3 py-2.5 text-sm text-slate-800 outline-none transition focus:border-indigo-400" onChange={(event) => updateFilter("cities", event.target.value.split(/[,，]/).map((item) => item.trim()).filter(Boolean))} placeholder="北京，上海" value={filters.cities.join(", ")} />
              </label>
              <label className="text-xs font-medium text-slate-500">学历要求
                <select className="mt-2 w-full rounded-xl border border-slate-200 bg-white px-3 py-2.5 text-sm text-slate-800 outline-none transition focus:border-indigo-400" onChange={(event) => updateFilter("education", event.target.value || null)} value={filters.education ?? ""}>
                  <option value="">不限学历</option>
                  <option value="大专">大专</option>
                  <option value="本科">本科</option>
                  <option value="硕士">硕士</option>
                  <option value="博士">博士</option>
                </select>
              </label>
              <label className="text-xs font-medium text-slate-500">经验要求
                <input className="mt-2 w-full rounded-xl border border-slate-200 bg-white px-3 py-2.5 text-sm text-slate-800 outline-none transition focus:border-indigo-400" onChange={(event) => updateFilter("experience", event.target.value || null)} placeholder="应届 / 1-3年" value={filters.experience ?? ""} />
              </label>
              <label className="text-xs font-medium text-slate-500">数据平台
                <input className="mt-2 w-full rounded-xl border border-slate-200 bg-white px-3 py-2.5 text-sm text-slate-800 outline-none transition focus:border-indigo-400" onChange={(event) => updateFilter("platform", event.target.value || null)} placeholder="BOSS / 拉勾" value={filters.platform ?? ""} />
              </label>
              </div>
              <div className="mt-4 flex flex-wrap items-end gap-4">
              <div>
                <p className="text-xs font-medium text-slate-500">岗位类型</p>
                <div className="mt-2 flex flex-wrap gap-2">
                  {["实习", "全职", "兼职", "校招", "社招"].map((jobType) => <label className={`cursor-pointer rounded-lg border px-3 py-2 text-xs transition ${filters.job_types.includes(jobType) ? "border-indigo-300 bg-indigo-50 text-indigo-700" : "border-slate-200 text-slate-500 hover:border-indigo-200"}`} key={jobType}><input checked={filters.job_types.includes(jobType)} className="sr-only" onChange={() => toggleJobType(jobType)} type="checkbox" />{jobType}</label>)}
                </div>
              </div>
              <label className="text-xs font-medium text-slate-500">最低薪资
                <input className="mt-2 w-24 rounded-xl border border-slate-200 bg-white px-3 py-2 text-sm text-slate-800 outline-none focus:border-indigo-400" min="0" onChange={(event) => updateFilter("salary_floor", event.target.value ? Number(event.target.value) : null)} type="number" value={filters.salary_floor ?? ""} />
              </label>
              <label className="text-xs font-medium text-slate-500">最高薪资
                <input className="mt-2 w-24 rounded-xl border border-slate-200 bg-white px-3 py-2 text-sm text-slate-800 outline-none focus:border-indigo-400" min="0" onChange={(event) => updateFilter("salary_ceiling", event.target.value ? Number(event.target.value) : null)} type="number" value={filters.salary_ceiling ?? ""} />
              </label>
              <label className="text-xs font-medium text-slate-500">发布起始
                <input className="mt-2 rounded-xl border border-slate-200 bg-white px-3 py-2 text-sm text-slate-800 outline-none focus:border-indigo-400" onChange={(event) => updateFilter("published_after", toIsoDate(event.target.value))} type="date" value={formatFilterDate(filters.published_after)} />
              </label>
              <label className="text-xs font-medium text-slate-500">发布结束
                <input className="mt-2 rounded-xl border border-slate-200 bg-white px-3 py-2 text-sm text-slate-800 outline-none focus:border-indigo-400" onChange={(event) => updateFilter("published_before", toIsoDate(event.target.value))} type="date" value={formatFilterDate(filters.published_before)} />
              </label>
                <button className="rounded-xl border border-slate-200 px-3 py-2.5 text-xs font-semibold text-slate-600 transition hover:bg-white dark:hover:bg-slate-800" onClick={() => setFilters(emptyFilters())} type="button">清空条件</button>
                <button className="rounded-xl bg-indigo-600 px-4 py-2.5 text-xs font-semibold text-white transition hover:bg-indigo-700 disabled:opacity-50" disabled={!selectedSession || savingContext} onClick={handleSaveContext} type="button">{savingContext ? "保存中…" : "保存并应用"}</button>
              </div>
              {!selectedSession && <p className="mt-3 text-xs text-slate-400">这些条件会在发送第一条消息时应用到新咨询。</p>}
            </div></AdvisorDialog>}
          </section>

          <section aria-label="对话消息" className="advisor-messages" ref={messagesViewportRef} onScroll={(event) => {
            const el = event.currentTarget;
            followMessages.current = shouldFollowMessages(el.scrollTop, el.clientHeight, el.scrollHeight);
            setAwayFromBottom(!followMessages.current);
          }}><div className="advisor-reading-column">
            {loadingSession && <div aria-label="正在加载会话" className="space-y-4 py-4"><div className="h-14 w-2/3 animate-pulse rounded-2xl bg-slate-100" /><div className="h-40 w-full animate-pulse rounded-2xl bg-slate-100" /></div>}
            {generating && <GenerationProgress sampleCount={retrievedSampleCount} stage={generationStage} statusLabel={generationStatusLabel} />}
            {(!selectedSession || messages.length === 0) && !loading && !loadingSession && (
              <div className="flex flex-1 flex-col items-center justify-center py-12 text-center">
                <div className="grid h-14 w-14 place-items-center rounded-2xl bg-indigo-50 text-2xl text-indigo-600">✦</div>
                <h3 className="mt-5 text-lg font-semibold text-slate-900">今天想了解哪个职业方向？</h3>
                <p className="mt-2 max-w-md text-sm leading-6 text-slate-500">我会结合已采集岗位与参考简历，整理市场需求和下一步行动。</p>
                <div className="mt-6 grid w-full max-w-2xl gap-2 text-left sm:grid-cols-2">
                  {quickPrompts.map((item) => <button className="group rounded-2xl border border-slate-200 bg-white p-3 text-left transition duration-150 hover:-translate-y-0.5 hover:border-indigo-300 hover:shadow-sm" key={item.prompt} onClick={() => applyPrompt(item.prompt)} type="button"><span className="mr-2 text-indigo-600">{item.icon}</span><span className="text-sm font-semibold text-slate-800">{item.title}</span><span className="mt-1 block truncate text-xs text-slate-400">{item.prompt}</span></button>)}
                </div>
              </div>
            )}
            {selectedSession && messages.length > 0 && !loadingSession && <div className="space-y-7">
              {selectedSession.message_has_more && <button className="mx-auto block rounded-full border border-slate-200 px-3 py-1.5 text-xs font-medium text-slate-500 transition hover:border-indigo-300 hover:text-indigo-700 disabled:opacity-50" disabled={loadingOlderMessages} onClick={() => void handleLoadOlderMessages()} type="button">{loadingOlderMessages ? "加载中…" : "加载更早消息"}</button>}
              {messages.map((message) => <MessageCard copied={copiedMessageId === message.id} expanded={!collapsedMessages.has(message.id)} key={message.id} message={message} sessionId={selectedSession.id} resumeId={selectedResumeId} onActionUpdate={handleActionUpdate} onCopy={handleCopy} onError={setError} onRegenerate={handleRegenerate} onEvidence={setEvidenceMessage} onToggleExpanded={toggleMessageExpanded} regenerating={generating || regeneratingId === message.id} />)}
              {!generating && suggestedFollowUps.length > 0 && <div className="animate-[advisorMessageIn_180ms_ease-out] border-t border-slate-200 pt-4"><p className="text-xs font-semibold text-slate-500">你还可以继续问</p><div className="mt-2 flex flex-wrap gap-2">{suggestedFollowUps.map((prompt) => <button className="rounded-full border border-slate-200 bg-white px-3 py-2 text-xs text-slate-600 transition hover:border-indigo-300 hover:bg-indigo-50 hover:text-indigo-700" key={prompt} onClick={() => applyPrompt(prompt)} type="button">{prompt}</button>)}</div></div>}
              <div ref={messagesEndRef} />
            </div>}
          </div></section>

          <div className="advisor-composer-zone">
          {awayFromBottom && <button className="advisor-latest" onClick={() => { followMessages.current = true; setAwayFromBottom(false); const el = messagesViewportRef.current; if (el) el.scrollTop = el.scrollHeight; }} type="button">↓ 回到最新消息</button>}
          <form className="advisor-composer" onSubmit={handleSend}>
            <textarea aria-label="向职业顾问提问" className="advisor-input" onChange={(event) => updateDraft(event.target.value)} onKeyDown={(event) => {
              if (event.key === "Enter" && !event.shiftKey && !event.nativeEvent.isComposing && event.keyCode !== 229) {
                event.preventDefault();
                if (!generating) event.currentTarget.form?.requestSubmit();
              }
            }} placeholder={generating ? "可以先写下一个问题，当前回答完成后再发送…" : "想了解什么职业方向？也可以让我结合简历分析…"} ref={inputRef} rows={1} value={input} />
            <div className="mt-2 flex flex-wrap items-center justify-between gap-3 px-1">
              <span className="text-[11px] text-slate-400">{generating ? "正在回答 · 可提前输入" : "Enter 发送 · Shift + Enter 换行"}</span>
              {generating ? (
                <button className="rounded-xl border border-rose-200 px-4 py-2.5 text-sm font-semibold text-rose-600 transition hover:bg-rose-50 disabled:opacity-50" disabled={stopping} onClick={handleStop} type="button">{stopping ? "停止中…" : "停止生成"}</button>
              ) : (
                <button className="rounded-xl bg-indigo-600 px-5 py-2.5 text-sm font-semibold text-white shadow-sm transition duration-150 hover:-translate-y-0.5 hover:bg-indigo-700 disabled:cursor-not-allowed disabled:opacity-50" disabled={!input.trim()} type="submit">发送</button>
              )}
            </div>
          </form>
          <p className="mt-2 text-center text-[11px] text-slate-400">建议供参考，岗位数据仅代表系统已采集样本。</p>
          </div>
        </div>
      </div>
      {evidenceMessage && <AdvisorDialog title="这条回答的依据" onClose={() => setEvidenceMessage(null)}><p className="mb-4 text-xs text-slate-500">回答时间：{formatMetadataDate(evidenceMessage.created_at)}</p><EvidenceContent message={evidenceMessage} /></AdvisorDialog>}
      {renameOpen && <div aria-modal="true" className="fixed inset-0 z-50 grid place-items-center bg-slate-950/40 p-4" role="dialog">
        <div className="w-full max-w-md rounded-2xl border border-slate-200 bg-white p-5 shadow-xl dark:bg-slate-900">
          <h2 className="text-lg font-semibold text-slate-900">重命名会话</h2>
          <input autoFocus className="mt-4 w-full rounded-xl border border-slate-200 bg-white px-3 py-2.5 text-sm text-slate-800 outline-none focus:border-indigo-400" maxLength={200} onChange={(event) => setRenameInput(event.target.value)} onKeyDown={(event) => { if (event.key === "Enter") void confirmRename(); }} value={renameInput} />
          <div className="mt-5 flex justify-end gap-2"><button className="rounded-lg border border-slate-200 px-3 py-2 text-sm text-slate-600" onClick={() => setRenameOpen(false)} type="button">取消</button><button className="rounded-lg bg-indigo-600 px-3 py-2 text-sm font-semibold text-white" onClick={() => void confirmRename()} type="button">保存</button></div>
        </div>
      </div>}
      {deleteOpen && <div aria-modal="true" className="fixed inset-0 z-50 grid place-items-center bg-slate-950/40 p-4" role="dialog">
        <div className="w-full max-w-md rounded-2xl border border-slate-200 bg-white p-5 shadow-xl dark:bg-slate-900">
          <h2 className="text-lg font-semibold text-slate-900">删除咨询记录？</h2>
          <p className="mt-2 text-sm leading-6 text-slate-500">将删除“{selectedSession?.title}”及其消息和岗位引用，岗位数据本身不会受影响。</p>
          <div className="mt-5 flex justify-end gap-2"><button className="rounded-lg border border-slate-200 px-3 py-2 text-sm text-slate-600" onClick={() => setDeleteOpen(false)} type="button">取消</button><button className="rounded-lg bg-rose-600 px-3 py-2 text-sm font-semibold text-white" onClick={() => void confirmDelete()} type="button">确认删除</button></div>
        </div>
      </div>}
    </div>
  );
}
