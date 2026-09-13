import { AGENT_STAGE_LABELS, type AgentRunState } from "./agent-event-adapter";

export function AgentStageTimeline({ run }: { run: AgentRunState }) {
  const stages = run.stageHistory;
  return <ol aria-label="Agent 工作阶段" className="mt-3 space-y-1.5">
    {stages.map((stage, index) => {
      const active = run.status === "running" && index === stages.length - 1;
      const completed = run.status === "completed" || index < stages.length - 1;
      const failed = run.status === "failed" && index === stages.length - 1;
      const cancelled = run.status === "cancelled" && index === stages.length - 1;
      return <li className={`flex items-center gap-2 rounded-lg px-2 py-1.5 text-xs transition-colors duration-200 ${active ? "bg-indigo-50 text-indigo-800 dark:bg-indigo-950/50 dark:text-indigo-200" : completed ? "text-emerald-700 dark:text-emerald-300" : "text-slate-400 dark:text-slate-500"}`} key={`${stage}-${index}`}>
        <span aria-hidden="true" className={`grid h-4 w-4 shrink-0 place-items-center rounded-full text-[10px] ${active ? "bg-indigo-500 text-white" : completed ? "bg-emerald-100 text-emerald-700 dark:bg-emerald-950 dark:text-emerald-300" : failed ? "bg-rose-100 text-rose-700 dark:bg-rose-950 dark:text-rose-300" : cancelled ? "bg-amber-100 text-amber-700 dark:bg-amber-950 dark:text-amber-300" : "bg-slate-100 text-slate-400 dark:bg-slate-800"}`}>
          {active ? <span className="h-1.5 w-1.5 animate-pulse rounded-full bg-white" /> : completed ? "✓" : failed ? "!" : cancelled ? "Ⅱ" : ""}
        </span>
        <span>{AGENT_STAGE_LABELS[stage]}</span>
        {active && <span className="ml-auto text-[11px] text-indigo-500">进行中</span>}
      </li>;
    })}
  </ol>;
}
