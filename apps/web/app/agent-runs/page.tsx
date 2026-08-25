"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";

import {
  createAgentRun,
  getAgentRuns,
  getResumes,
  type AgentRun,
  type Resume,
} from "../../lib/api";

const statusLabels: Record<AgentRun["status"], string> = {
  PENDING: "待启动",
  RUNNING: "运行中",
  PAUSED: "已暂停",
  WAITING_FOR_USER: "等待审批",
  COMPLETED: "已完成",
  CANCELLED: "已取消",
  FAILED: "失败",
  TIMED_OUT: "已超时",
};

export default function AgentRunsPage() {
  const router = useRouter();
  const [runs, setRuns] = useState<AgentRun[]>([]);
  const [resumes, setResumes] = useState<Resume[]>([]);
  const [resumeId, setResumeId] = useState("");
  const [goal, setGoal] = useState("帮我找匹配度 80 分以上的 AI Agent 实习岗位");
  const [autoStart, setAutoStart] = useState(true);
  const [loading, setLoading] = useState(true);
  const [creating, setCreating] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    Promise.all([getAgentRuns(), getResumes()])
      .then(([runResponse, resumeResponse]) => {
        setRuns(runResponse.items);
        setResumes(resumeResponse.items);
        const selected =
          resumeResponse.items.find((resume) => resume.is_default) ?? resumeResponse.items[0];
        setResumeId(selected?.id ?? "");
      })
      .catch(() => setError("无法加载 Agent Run，请确认 API 服务已启动。"))
      .finally(() => setLoading(false));
  }, []);

  async function handleCreate() {
    if (!goal.trim() || !resumeId) return;
    setCreating(true);
    setError(null);
    try {
      const run = await createAgentRun({
        goal: goal.trim(),
        resume_id: resumeId,
        auto_start: autoStart,
      });
      router.push(`/agent-runs/${run.id}`);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Agent Run 创建失败。");
    } finally {
      setCreating(false);
    }
  }

  return (
    <div className="mx-auto max-w-7xl space-y-8">
      <header>
        <p className="eyebrow">Agent Runtime</p>
        <h1 className="mt-3 text-3xl font-semibold tracking-tight">Agent Runs</h1>
        <p className="mt-3 max-w-3xl text-slate-500">
          用自然语言发起求职目标，查看 Planner、Tool 调用、状态检查点与人工审批轨迹。
        </p>
      </header>

      <section className="panel">
        <div className="flex flex-wrap items-end justify-between gap-4">
          <div><p className="eyebrow">New Run</p><h2 className="mt-2 text-xl font-semibold">启动求职 Agent</h2></div>
          <span className="rounded-full bg-indigo-50 px-3 py-1 text-xs font-medium text-indigo-700">Single Orchestrator</span>
        </div>
        <label className="mt-6 block text-sm font-medium text-slate-700">
          求职目标
          <textarea className="mt-2 min-h-28 w-full rounded-xl border border-slate-200 px-4 py-3 font-normal outline-none focus:border-indigo-500 focus:ring-4 focus:ring-indigo-100" onChange={(event) => setGoal(event.target.value)} value={goal} />
        </label>
        <div className="mt-4 grid gap-4 md:grid-cols-2">
          <label className="text-sm font-medium text-slate-700">
            使用简历
            <select className="mt-2 w-full rounded-xl border border-slate-200 bg-white px-4 py-3 font-normal outline-none focus:border-indigo-500 focus:ring-4 focus:ring-indigo-100" onChange={(event) => setResumeId(event.target.value)} value={resumeId}>
              {resumes.length === 0 && <option value="">暂无简历</option>}
              {resumes.map((resume) => <option key={resume.id} value={resume.id}>{resume.name}{resume.is_default ? "（默认）" : ""}</option>)}
            </select>
          </label>
          <label className="flex items-center gap-3 self-end rounded-xl border border-slate-200 px-4 py-3 text-sm text-slate-700">
            <input checked={autoStart} className="h-4 w-4 accent-indigo-600" onChange={(event) => setAutoStart(event.target.checked)} type="checkbox" />
            创建后立即执行到人工审批节点
          </label>
        </div>
        <button className="mt-5 rounded-xl bg-indigo-600 px-5 py-3 text-sm font-medium text-white transition hover:bg-indigo-700 disabled:cursor-not-allowed disabled:opacity-50" disabled={creating || !goal.trim() || !resumeId} onClick={() => void handleCreate()} type="button">
          {creating ? "Agent 执行中…" : "创建 Agent Run"}
        </button>
      </section>

      {error && <div className="rounded-xl border border-rose-200 bg-rose-50 p-4 text-rose-800">{error}</div>}

      <section>
        <div className="mb-4 flex items-end justify-between gap-4">
          <div><p className="eyebrow">Run History</p><h2 className="mt-2 text-xl font-semibold">执行记录</h2></div>
          <p className="text-sm text-slate-500">{runs.length} 个 Run</p>
        </div>
        {loading && <div className="panel text-center text-slate-500">加载中…</div>}
        {!loading && runs.length === 0 && <div className="panel text-center text-slate-500">还没有 Agent Run。</div>}
        <div className="grid gap-4 lg:grid-cols-2">
          {runs.map((run) => (
            <Link className="panel block transition hover:-translate-y-0.5 hover:border-indigo-200 hover:shadow-md" href={`/agent-runs/${run.id}`} key={run.id}>
              <div className="flex items-start justify-between gap-4">
                <div><h3 className="line-clamp-2 font-semibold text-slate-900">{run.input.goal ?? "未命名目标"}</h3><p className="mt-2 text-xs text-slate-500">{new Date(run.created_at).toLocaleString("zh-CN")}</p></div>
                <span className="whitespace-nowrap rounded-full bg-indigo-50 px-3 py-1 text-xs font-medium text-indigo-700">{statusLabels[run.status]}</span>
              </div>
              <div className="mt-5 flex items-center justify-between border-t border-slate-100 pt-4 text-sm text-slate-500"><span>{run.steps.length} steps</span><span>{run.campaign_id ? "Campaign 已创建" : "尚无 Campaign"}</span></div>
            </Link>
          ))}
        </div>
      </section>
    </div>
  );
}
