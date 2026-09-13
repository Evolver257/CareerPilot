import type { AgentConnectionState } from "./agent-event-adapter";

export function AgentConnectionStatus({ state, attempt = 0 }: { state: AgentConnectionState; attempt?: number }) {
  if (state === "connected") return null;
  const copy = state === "reconnecting"
    ? `正在重新连接${attempt > 0 ? ` ${attempt}/5` : ""}`
    : state === "recovered"
      ? "已恢复连接"
      : "连接暂时中断，已保存当前进度";
  const className = state === "recovered"
    ? "border-emerald-200 bg-emerald-50 text-emerald-700 dark:border-emerald-900/70 dark:bg-emerald-950/30 dark:text-emerald-300"
    : state === "offline"
      ? "border-rose-200 bg-rose-50 text-rose-700 dark:border-rose-900/70 dark:bg-rose-950/30 dark:text-rose-300"
      : "border-amber-200 bg-amber-50 text-amber-700 dark:border-amber-900/70 dark:bg-amber-950/30 dark:text-amber-300";
  return <p className={`rounded-lg border px-2.5 py-1.5 text-xs ${className}`} role="status">{copy}</p>;
}
