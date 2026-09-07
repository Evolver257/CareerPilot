"use client";

import Link from "next/link";
import { useParams } from "next/navigation";
import { useCallback, useEffect, useState } from "react";

import {
  browserTaskAction,
  browserTaskWebSocketUrl,
  getBrowserTask,
  resumeBrowserTask,
  simulateBrowserExtension,
  type BrowserTask,
} from "../../../lib/api";
import { developerMode } from "../../../lib/workspaces";
import { launchDeliveryTasks } from "../../../lib/delivery-bridge";

const statusLabels: Record<BrowserTask["status"], string> = {
  PENDING: "待启动",
  CONNECTING: "等待 Extension",
  RUNNING: "执行中",
  WAITING_FOR_USER: "等待人工处理",
  COMPLETED: "已完成",
  CANCELLED: "已取消",
  FAILED: "失败",
};

export default function BrowserTaskDetailPage() {
  const params = useParams<{ id: string }>();
  const [task, setTask] = useState<BrowserTask | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const load = useCallback(async () => {
    try { setTask(await getBrowserTask(params.id)); } catch (reason) { setError(reason instanceof Error ? reason.message : "Browser Task 加载失败。"); }
  }, [params.id]);

  useEffect(() => { void load(); }, [load]);
  const taskStatus = task?.status;
  useEffect(() => {
    if (!taskStatus || !["CONNECTING", "RUNNING"].includes(taskStatus)) return;
    const timer = window.setInterval(() => void load(), 1000);
    return () => window.clearInterval(timer);
  }, [load, taskStatus]);

  async function action(name: "start" | "cancel") { setBusy(true); try { setTask(await browserTaskAction(params.id, name)); } catch (reason) { setError(reason instanceof Error ? reason.message : "Browser Task 操作失败。"); } finally { setBusy(false); } }
  async function resume() { setBusy(true); try { setTask(await resumeBrowserTask(params.id, "resolved", "用户已完成页面处理")); } catch (reason) { setError(reason instanceof Error ? reason.message : "Browser Task 恢复失败。"); } finally { setBusy(false); } }
  async function simulate() { setBusy(true); try { setTask(await simulateBrowserExtension(params.id)); } catch (reason) { setError(reason instanceof Error ? reason.message : "Mock Extension 执行失败。"); } finally { setBusy(false); } }
  async function launch() {
    if (!task || (task.platform !== "boss" && task.platform !== "zhaopin")) return;
    setBusy(true); setError(null);
    try {
      const actions = task.payload.actions as { url?: string }[] | undefined;
      const url = actions?.[0]?.url;
      if (!url) throw new Error("任务缺少岗位原页");
      await launchDeliveryTasks([{ task_id: task.id, platform: task.platform, url }]);
      await load();
    } catch (reason) { setError(reason instanceof Error ? reason.message : "扩展启动失败"); }
    finally { setBusy(false); }
  }

  if (!task) return <div className="panel mx-auto max-w-7xl text-slate-500">{error ?? "加载 Browser Task…"}</div>;
  const currentAction = task.current_action as { action?: string; url?: string; target?: { name?: string }; metadata?: { reason?: string } };
  const terminal = ["COMPLETED", "CANCELLED", "FAILED"].includes(task.status);
  const realPlatform = task.platform === "boss" || task.platform === "zhaopin";
  return (
    <div className="mx-auto max-w-7xl space-y-8">
      <header className="panel">
        <Link className="text-sm font-medium text-indigo-700" href="/delivery">← 投递执行与记录</Link>
        <div className="mt-5 flex flex-wrap items-start justify-between gap-4"><div><p className="eyebrow">Browser Task Trace</p><h1 className="mt-3 text-2xl font-semibold">{task.platform} 投递执行</h1><p className="mt-2 font-mono text-xs text-slate-400">{task.id}</p></div><span className="rounded-full bg-indigo-50 px-4 py-2 text-sm font-semibold text-indigo-700">{statusLabels[task.status]}</span></div>
        <div className="mt-6 flex flex-wrap gap-3 border-t border-slate-100 pt-5">
          {realPlatform && ["PENDING", "CONNECTING"].includes(task.status) && <button className="rounded-xl bg-indigo-600 px-4 py-2 text-sm font-medium text-white" disabled={busy} onClick={() => void launch()} type="button">通过扩展启动投递</button>}
          {developerMode && !realPlatform && task.status === "PENDING" && <button className="rounded-xl bg-indigo-600 px-4 py-2 text-sm font-medium text-white" disabled={busy} onClick={() => void action("start")} type="button">Start</button>}
          {developerMode && !realPlatform && task.status === "CONNECTING" && <button className="rounded-xl bg-indigo-600 px-4 py-2 text-sm font-medium text-white" disabled={busy} onClick={() => void simulate()} type="button">运行本地 Extension</button>}
          {task.status === "WAITING_FOR_USER" && <button className="rounded-xl bg-indigo-600 px-4 py-2 text-sm font-medium text-white" disabled={busy} onClick={() => void resume()} type="button">已处理，继续任务</button>}
          {!terminal && <button className="rounded-xl border border-rose-200 bg-rose-50 px-4 py-2 text-sm font-medium text-rose-700" disabled={busy} onClick={() => void action("cancel")} type="button">取消任务</button>}
          {developerMode && !realPlatform && <Link className="rounded-xl border border-slate-200 px-4 py-2 text-sm font-medium text-slate-700" href={`/mock-platform/jobs/${String(task.payload.context && (task.payload.context as Record<string, unknown>).job_id)}?task=${task.id}`}>打开本地 Job Site</Link>}
        </div>
        {realPlatform && !terminal && <p className="mt-3 text-sm text-slate-500">需要人工处理时，请切换到扩展已经打开的招聘标签页，完成登录、验证或简历确认，再回来继续任务。结果不明确时不会重复点击投递。</p>}
      </header>
      {error && <div className="rounded-xl border border-rose-200 bg-rose-50 p-4 text-rose-800">{error}</div>}
      {task.status === "WAITING_FOR_USER" && <section className="panel border-amber-200 bg-amber-50/50"><p className="eyebrow text-amber-700">Human in the Loop</p><h2 className="mt-2 text-xl font-semibold">需要人工处理</h2><p className="mt-3 text-sm text-slate-600">{currentAction.metadata?.reason ?? task.failure_reason}</p><p className="mt-3 text-sm text-slate-500">处理页面后，点击“已处理，继续任务”。若此前已点击投递但结果不明确，请先在招聘页面核验，不要重复投递。</p></section>}
      {developerMode && <section className="grid gap-4 md:grid-cols-4"><div className="panel"><p className="text-xs text-slate-400">Platform</p><p className="mt-2 font-semibold">{task.platform}</p></div><div className="panel"><p className="text-xs text-slate-400">Scenario</p><p className="mt-2 font-semibold">{task.scenario}</p></div><div className="panel"><p className="text-xs text-slate-400">Actions</p><p className="mt-2 font-semibold">{task.action_sequence}</p></div><div className="panel"><p className="text-xs text-slate-400">Application</p><p className="mt-2 font-mono text-xs">{task.application_id.slice(0, 12)}</p></div></section>}
      {developerMode && currentAction.action && <section className="panel"><div className="flex items-center justify-between gap-4"><div><p className="eyebrow">Current Action</p><h2 className="mt-2 text-xl font-semibold">{currentAction.action}</h2></div><span className="rounded-full bg-slate-100 px-3 py-1 text-xs text-slate-600">{currentAction.target?.name ?? currentAction.url ?? "structured action"}</span></div><pre className="mt-5 overflow-auto rounded-xl bg-slate-950 p-4 text-xs leading-6 text-slate-200">{JSON.stringify(currentAction, null, 2)}</pre></section>}
      <section className="panel"><div className="flex items-end justify-between"><div><p className="eyebrow">Extension Event Log</p><h2 className="mt-2 text-xl font-semibold">Browser Events</h2></div><span className="text-sm text-slate-500">{task.events.length} events</span></div><ol className="mt-5 divide-y divide-slate-100">{task.events.map((event) => <li className="flex flex-wrap items-center justify-between gap-3 py-3 text-sm" key={event.id}><span><span className="font-mono font-medium text-slate-700">{event.event_type}</span>{event.sequence && <span className="ml-3 text-xs text-slate-400">action {event.sequence}</span>}</span><time className="text-xs text-slate-400">{new Date(event.created_at).toLocaleString("zh-CN")}</time></li>)}</ol></section>
      {developerMode && <p className="text-xs text-slate-400">Extension WebSocket: {browserTaskWebSocketUrl(task.id)}</p>}
    </div>
  );
}
