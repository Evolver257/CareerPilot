import { useState } from "react";

import type { AgentToolState } from "./agent-event-adapter";

export function AgentToolCall({ tool }: { tool: AgentToolState }) {
  const [expanded, setExpanded] = useState(tool.status !== "completed");
  const statusLabel = tool.status === "completed" ? "已完成" : tool.status === "failed" ? "失败" : "进行中";
  const statusClass = tool.status === "completed" ? "text-emerald-600 dark:text-emerald-300" : tool.status === "failed" ? "text-rose-600 dark:text-rose-300" : "text-indigo-600 dark:text-indigo-300";
  return <details className="rounded-xl border border-slate-200 bg-white/70 dark:border-slate-700 dark:bg-slate-900/60" open={expanded}>
    <summary className="flex cursor-pointer list-none items-center gap-2 px-3 py-2.5 text-xs font-medium text-slate-700 dark:text-slate-200" onClick={(event) => { event.preventDefault(); setExpanded((value) => !value); }}>
      <span aria-hidden="true" className={`h-1.5 w-1.5 rounded-full ${tool.status === "failed" ? "bg-rose-500" : tool.status === "completed" ? "bg-emerald-500" : "animate-pulse bg-indigo-500"}`} />
      <span className="min-w-0 flex-1 truncate">{tool.displayName}</span>
      {tool.status === "completed" && <span className="hidden max-w-[45%] truncate text-[11px] font-normal text-slate-500 sm:inline dark:text-slate-400">· {tool.resultSummary}</span>}
      <span className={statusClass}>{statusLabel}</span>
    </summary>
    <div className="space-y-1 border-t border-slate-100 px-3 py-2 text-[11px] leading-5 text-slate-500 dark:border-slate-800 dark:text-slate-400">
      <p>输入：{tool.inputSummary}</p>
      <p>结果：{tool.resultSummary}</p>
      {tool.durationMs !== null && <p>耗时：{(tool.durationMs / 1000).toFixed(1)} 秒</p>}
      {tool.status === "failed" && <p className="text-rose-600 dark:text-rose-300">{tool.retryable ? "该操作可以重试" : "该操作未自动重试"}</p>}
    </div>
  </details>;
}
