import { useEffect, useMemo, useState } from "react";

import { AgentConnectionStatus } from "./agent-connection-status";
import { AgentStageTimeline } from "./agent-stage-timeline";
import { AgentToolCall } from "./agent-tool-call";
import type { AgentRunState } from "./agent-event-adapter";

function durationSeconds(run: AgentRunState) {
  if (typeof run.latencyMs === "number" && Number.isFinite(run.latencyMs) && run.latencyMs > 0) {
    return (run.latencyMs / 1000).toFixed(1);
  }
  const start = Date.parse(run.startedAt);
  const end = Date.parse(run.completedAt ?? new Date().toISOString());
  if (!Number.isFinite(start) || !Number.isFinite(end)) return "0.0";
  return Math.max(0, (end - start) / 1000).toFixed(1);
}

export function AgentRunStatus({
  run,
}: {
  run: AgentRunState;
}) {
  const [expanded, setExpanded] = useState(run.status === "running" || run.status === "failed" || run.status === "cancelled");
  const [interacted, setInteracted] = useState(false);
  const completed = run.status === "completed";
  const failed = run.status === "failed";
  const cancelled = run.status === "cancelled";
  useEffect(() => {
    if (completed && !interacted) setExpanded(false);
  }, [completed, interacted]);
  const toolCount = run.tools.length;
  const evidenceCount = run.evidenceCount;
  const summary = useMemo(() => {
    if (completed) return `已完成 · ${toolCount} 次工具调用 · ${evidenceCount} 条证据 · ${durationSeconds(run)} 秒`;
    if (failed) return "执行失败，可保留已生成内容并重新尝试";
    if (cancelled) return "已停止 · 已保留已经生成的内容";
    return `${run.label}${run.sampleCount > 0 ? ` · 已发现 ${run.sampleCount} 个岗位样本` : ""}`;
  }, [cancelled, completed, evidenceCount, failed, run, toolCount]);
  return <section aria-label="Agent 工作状态" className={`agent-run-status mb-4 rounded-2xl border p-3 transition-colors duration-200 ${failed ? "border-rose-200 bg-rose-50/60 dark:border-rose-900/70 dark:bg-rose-950/20" : cancelled ? "border-amber-200 bg-amber-50/60 dark:border-amber-900/70 dark:bg-amber-950/20" : "border-slate-200 bg-slate-50/70 dark:border-slate-700 dark:bg-slate-900/60"}`}>
    <div className="flex items-center gap-2">
      {!completed && !failed && !cancelled && <span aria-hidden="true" className="relative flex h-2.5 w-2.5 shrink-0"><span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-indigo-400 opacity-40" /><span className="relative inline-flex h-2.5 w-2.5 rounded-full bg-indigo-500" /></span>}
      {completed && <span aria-hidden="true" className="text-sm text-emerald-600">✓</span>}
      {failed && <span aria-hidden="true" className="text-sm text-rose-600">!</span>}
      {cancelled && <span aria-hidden="true" className="text-sm text-amber-600">Ⅱ</span>}
      <p className="min-w-0 flex-1 truncate text-sm font-semibold text-slate-800 dark:text-slate-100">{completed || failed || cancelled ? summary : run.label}</p>
      <button aria-expanded={expanded} className="shrink-0 rounded-lg px-2 py-1 text-xs font-medium text-slate-500 transition hover:bg-white hover:text-indigo-700 dark:hover:bg-slate-800 dark:hover:text-indigo-300" onClick={() => { setInteracted(true); setExpanded((value) => !value); }} type="button">{expanded ? "收起过程" : "查看执行过程"}</button>
    </div>
    {!completed && !failed && !cancelled && <p className="mt-1 pl-5 text-xs text-slate-500 dark:text-slate-400">{run.detail}{run.sampleCount > 0 ? ` · 已检索 ${run.sampleCount} 个岗位样本` : ""}</p>}
    {expanded && <div className="mt-3 border-t border-slate-200/80 pt-3 dark:border-slate-700/80">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <p className="text-xs text-slate-500 dark:text-slate-400">{completed ? `${toolCount} 次工具调用 · ${evidenceCount} 条证据 · 用时 ${durationSeconds(run)} 秒` : "状态来自实际 Agent 事件"}</p>
        <AgentConnectionStatus state={run.connection} attempt={run.reconnectAttempt} />
      </div>
      <AgentStageTimeline run={run} />
      {run.tools.length > 0 && <div className="mt-3 space-y-2"><p className="text-xs font-semibold text-slate-600 dark:text-slate-300">工具调用 · {run.tools.length} 次</p>{run.tools.map((tool) => <AgentToolCall key={tool.id} tool={tool} />)}</div>}
    </div>}
  </section>;
}
