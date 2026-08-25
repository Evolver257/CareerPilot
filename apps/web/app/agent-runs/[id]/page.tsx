"use client";

import Link from "next/link";
import { useParams } from "next/navigation";
import { useCallback, useEffect, useState } from "react";

import {
  agentRunAction,
  getAgentRun,
  resumeAgentRun,
  type AgentCandidate,
  type AgentRun,
  type AgentRunStatus,
} from "../../../lib/api";

const statusLabels: Record<AgentRunStatus, string> = {
  PENDING: "待启动",
  RUNNING: "运行中",
  PAUSED: "已暂停",
  WAITING_FOR_USER: "等待审批",
  COMPLETED: "已完成",
  CANCELLED: "已取消",
  FAILED: "失败",
  TIMED_OUT: "已超时",
};

const toolLabels: Record<string, string> = {
  search_jobs: "Search Jobs",
  analyze_job: "Analyze Jobs",
  retrieve_resume: "Retrieve Resume",
  rank_jobs: "Rank Jobs",
  create_campaign: "Create Campaign",
  request_approval: "Request Approval",
  queue_application: "Queue Applications",
};

function JsonBlock({ value }: { value: Record<string, unknown> }) {
  return (
    <pre className="mt-2 max-h-80 overflow-auto whitespace-pre-wrap break-all rounded-xl bg-slate-950 p-4 text-xs leading-6 text-slate-200">
      {JSON.stringify(value, null, 2)}
    </pre>
  );
}

export default function AgentRunDetailPage() {
  const params = useParams<{ id: string }>();
  const runId = params.id;
  const [run, setRun] = useState<AgentRun | null>(null);
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      const response = await getAgentRun(runId);
      setRun(response);
      setSelected((current) => {
        if (current.size > 0) return current;
        return new Set((response.output.candidates ?? []).map((item) => item.job_id));
      });
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Agent Run 加载失败。");
    } finally {
      setLoading(false);
    }
  }, [runId]);

  useEffect(() => {
    void load();
  }, [load]);

  useEffect(() => {
    if (run?.status !== "RUNNING") return;
    const timer = window.setInterval(() => void load(), 1200);
    return () => window.clearInterval(timer);
  }, [load, run?.status]);

  async function handleAction(action: "start" | "pause" | "cancel") {
    if (!run) return;
    setBusy(true);
    setError(null);
    try {
      setRun(await agentRunAction(run.id, action));
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Agent 操作失败。");
    } finally {
      setBusy(false);
    }
  }

  async function handleResume(payload: { approved?: boolean; selected_job_ids?: string[] }) {
    if (!run) return;
    setBusy(true);
    setError(null);
    try {
      setRun(await resumeAgentRun(run.id, payload));
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Agent 恢复失败。");
    } finally {
      setBusy(false);
    }
  }

  function toggleCandidate(candidate: AgentCandidate) {
    setSelected((current) => {
      const next = new Set(current);
      if (next.has(candidate.job_id)) next.delete(candidate.job_id);
      else next.add(candidate.job_id);
      return next;
    });
  }

  if (loading) return <div className="panel mx-auto max-w-7xl text-center text-slate-500">加载 Agent Trace…</div>;
  if (!run) return <div className="panel mx-auto max-w-7xl text-rose-700">{error ?? "Agent Run 不存在。"}</div>;

  const candidates = run.output.candidates ?? [];
  const canCancel = !["COMPLETED", "CANCELLED", "FAILED", "TIMED_OUT"].includes(run.status);

  return (
    <div className="mx-auto max-w-7xl space-y-8">
      <header className="panel">
        <Link className="text-sm font-medium text-indigo-700" href="/agent-runs">← Agent Runs</Link>
        <div className="mt-5 flex flex-wrap items-start justify-between gap-5">
          <div className="max-w-4xl">
            <p className="eyebrow">Agent Run Trace</p>
            <h1 className="mt-3 text-2xl font-semibold tracking-tight">{run.input.goal ?? "未命名目标"}</h1>
            <p className="mt-3 font-mono text-xs text-slate-400">Run ID · {run.id}</p>
          </div>
          <span className="rounded-full bg-indigo-50 px-4 py-2 text-sm font-semibold text-indigo-700">{statusLabels[run.status]}</span>
        </div>
        <div className="mt-6 flex flex-wrap gap-3 border-t border-slate-100 pt-5">
          {run.status === "PENDING" && <button className="rounded-xl bg-indigo-600 px-4 py-2 text-sm font-medium text-white disabled:opacity-50" disabled={busy} onClick={() => void handleAction("start")} type="button">Start</button>}
          {run.status === "RUNNING" && <button className="rounded-xl border border-slate-200 bg-white px-4 py-2 text-sm font-medium disabled:opacity-50" disabled={busy} onClick={() => void handleAction("pause")} type="button">Pause</button>}
          {run.status === "PAUSED" && <button className="rounded-xl bg-indigo-600 px-4 py-2 text-sm font-medium text-white disabled:opacity-50" disabled={busy} onClick={() => void handleResume({})} type="button">Resume</button>}
          {canCancel && <button className="rounded-xl border border-rose-200 bg-rose-50 px-4 py-2 text-sm font-medium text-rose-700 disabled:opacity-50" disabled={busy} onClick={() => void handleAction("cancel")} type="button">Cancel</button>}
          {run.campaign_id && <Link className="rounded-xl border border-slate-200 px-4 py-2 text-sm font-medium text-slate-700" href={`/campaigns/${run.campaign_id}`}>查看 Campaign</Link>}
        </div>
      </header>

      {error && <div className="rounded-xl border border-rose-200 bg-rose-50 p-4 text-rose-800">{error}</div>}
      {run.error && <div className="rounded-xl border border-rose-200 bg-rose-50 p-4 text-rose-800"><span className="font-semibold">Runtime Error · </span>{run.error}</div>}

      {run.status === "WAITING_FOR_USER" && (
        <section className="panel border-amber-200 bg-amber-50/40">
          <div className="flex flex-wrap items-start justify-between gap-4">
            <div><p className="eyebrow text-amber-700">Human in the Loop</p><h2 className="mt-2 text-xl font-semibold">{run.output.prompt ?? "请选择要加入投递队列的职位"}</h2></div>
            <span className="rounded-full bg-white px-3 py-1 text-xs font-medium text-amber-700">已选 {selected.size} / {candidates.length}</span>
          </div>
          <div className="mt-5 grid gap-3 lg:grid-cols-2">
            {candidates.map((candidate) => (
              <label className="flex cursor-pointer items-start gap-3 rounded-xl border border-amber-200 bg-white p-4" key={candidate.job_id}>
                <input checked={selected.has(candidate.job_id)} className="mt-1 h-4 w-4 accent-indigo-600" onChange={() => toggleCandidate(candidate)} type="checkbox" />
                <span className="min-w-0"><span className="block font-semibold text-slate-900">{candidate.title}</span><span className="mt-1 block text-sm text-slate-500">匹配度 {candidate.score.toFixed(1)} · {candidate.recommendation}</span></span>
              </label>
            ))}
          </div>
          {candidates.length === 0 && <p className="mt-5 text-sm text-slate-500">当前阈值下没有候选职位，可以结束本次 Run。</p>}
          <div className="mt-5 flex flex-wrap gap-3">
            <button className="rounded-xl bg-indigo-600 px-5 py-3 text-sm font-medium text-white disabled:opacity-50" disabled={busy || selected.size === 0} onClick={() => void handleResume({ approved: true, selected_job_ids: [...selected] })} type="button">批准并加入队列</button>
            <button className="rounded-xl border border-slate-200 bg-white px-5 py-3 text-sm font-medium text-slate-700 disabled:opacity-50" disabled={busy} onClick={() => void handleResume({ approved: false })} type="button">拒绝并结束</button>
          </div>
        </section>
      )}

      <section>
        <div className="mb-4 flex items-end justify-between gap-4"><div><p className="eyebrow">Execution Trace</p><h2 className="mt-2 text-xl font-semibold">Agent Steps</h2></div><p className="text-sm text-slate-500">{run.steps.length} / {run.max_steps} steps</p></div>
        <ol className="space-y-4">
          {run.steps.map((step) => (
            <li className="panel" key={step.id}>
              <div className="flex flex-wrap items-center justify-between gap-4">
                <div className="flex items-center gap-4"><span className="grid h-10 w-10 place-items-center rounded-full bg-indigo-50 font-mono text-sm font-semibold text-indigo-700">{step.sequence}</span><div><h3 className="font-semibold">{toolLabels[step.tool_name ?? ""] ?? step.tool_name ?? step.step_type}</h3><p className="mt-1 text-xs text-slate-400">attempt {step.attempt}</p></div></div>
                <div className="flex items-center gap-3 text-xs"><span className="rounded-full bg-slate-100 px-3 py-1 font-medium text-slate-600">{step.latency_ms.toFixed(2)} ms</span><span className={`rounded-full px-3 py-1 font-medium ${step.status === "COMPLETED" ? "bg-emerald-50 text-emerald-700" : step.status === "FAILED" ? "bg-rose-50 text-rose-700" : "bg-amber-50 text-amber-700"}`}>{step.status}</span></div>
              </div>
              {step.error && <p className="mt-4 rounded-xl bg-rose-50 p-3 text-sm text-rose-700">{step.error}</p>}
              <div className="mt-5 grid gap-4 xl:grid-cols-2">
                <details><summary className="cursor-pointer text-sm font-semibold text-slate-700">Tool Input</summary><JsonBlock value={step.input} /></details>
                <details><summary className="cursor-pointer text-sm font-semibold text-slate-700">Tool Output</summary><JsonBlock value={step.output} /></details>
              </div>
            </li>
          ))}
        </ol>
      </section>

      <section className="panel">
        <div className="flex items-end justify-between gap-4"><div><p className="eyebrow">Event Log</p><h2 className="mt-2 text-xl font-semibold">Agent Events</h2></div><p className="text-sm text-slate-500">{run.events.length} events</p></div>
        <ol className="mt-5 divide-y divide-slate-100">
          {run.events.map((event) => <li className="flex flex-wrap items-center justify-between gap-3 py-3 text-sm" key={event.id}><span className="font-mono font-medium text-slate-700">{event.event_type}</span><time className="text-xs text-slate-400">{new Date(event.created_at).toLocaleString("zh-CN")}</time></li>)}
        </ol>
      </section>
    </div>
  );
}
