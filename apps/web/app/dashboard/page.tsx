"use client";

import Link from "next/link";
import { useEffect, useState } from "react";

import { StatCard } from "../../components/stat-card";
import { getDashboard, type DashboardResponse } from "../../lib/api";

const statusLabels: Record<string, string> = {
  WAITING_APPROVAL: "等待确认",
  APPROVED: "已批准",
  QUEUED: "已排队",
  EXECUTING: "执行中",
  SUBMITTED: "已投递",
  PAUSED: "已暂停",
  CAPTCHA_REQUIRED: "需要验证码",
  LOGIN_REQUIRED: "需要登录",
  PLATFORM_LIMIT: "平台限制",
  DOM_CHANGED: "页面变化",
  RISK_CONTROL: "风控暂停",
  UNKNOWN_STATE: "未知页面",
  FAILED: "失败",
};

function formatCost(cost: number | null) {
  return cost === null ? "未计费" : `$${cost.toFixed(4)}`;
}

export default function DashboardPage() {
  const [dashboard, setDashboard] = useState<DashboardResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    getDashboard()
      .then(setDashboard)
      .catch((reason) => setError(reason instanceof Error ? reason.message : "Dashboard 加载失败。"))
      .finally(() => setLoading(false));
  }, []);

  if (loading) {
    return <div className="panel mx-auto max-w-7xl text-center text-slate-500">正在加载 Dashboard 统计…</div>;
  }

  if (!dashboard) {
    return <div className="panel mx-auto max-w-7xl text-rose-700">{error ?? "Dashboard 暂不可用。"}</div>;
  }

  const { summary, agent, token_usage: usage } = dashboard;
  const maxFunnel = Math.max(...dashboard.funnel.map((stage) => stage.count), 1);

  return (
    <div className="mx-auto max-w-7xl space-y-8">
      <header className="flex flex-wrap items-end justify-between gap-5">
        <div>
          <p className="eyebrow">CareerPilot / Product Dashboard</p>
          <h1 className="mt-3 text-3xl font-semibold tracking-tight sm:text-4xl">求职工作台</h1>
          <p className="mt-3 max-w-3xl text-slate-500">用一个可解释的工作台查看职位、匹配、投递漏斗、Agent Trace 与 LLM 运行成本。</p>
        </div>
        <p className="text-xs text-slate-400">刷新于 {new Date(dashboard.refreshed_at).toLocaleString("zh-CN")}</p>
      </header>

      {error && <div className="rounded-xl border border-amber-200 bg-amber-50 p-4 text-amber-800">{error}</div>}

      <section className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
        <StatCard label="发现职位" value={summary.jobs_total} hint="Jobs Repository" />
        <StatCard label="高匹配职位" value={summary.high_match_jobs} hint="Final score ≥ 70" />
        <StatCard label="投递计划" value={summary.campaigns_total} hint={`${summary.campaign_candidates} 个候选职位`} />
        <StatCard label="需要处理" value={summary.attention_required} hint="验证码、风控、错误或未知页面" />
      </section>

      <section className="grid gap-6 xl:grid-cols-[1.5fr_1fr]">
        <div className="panel">
          <div className="flex flex-wrap items-end justify-between gap-4"><div><p className="eyebrow">Application Funnel</p><h2 className="mt-2 text-xl font-semibold">求职漏斗</h2></div><Link className="text-sm font-medium text-indigo-700" href="/applications">查看投递状态 →</Link></div>
          <div className="mt-7 space-y-4">
            {dashboard.funnel.map((stage) => (
              <div key={stage.key}>
                <div className="mb-1 flex items-center justify-between gap-3 text-sm"><span className="font-medium text-slate-700">{stage.label}</span><span className="text-slate-500">{stage.count}{stage.conversion_rate === null ? "" : ` · ${stage.conversion_rate}%`}</span></div>
                <div className="h-3 overflow-hidden rounded-full bg-slate-100"><div className="h-full rounded-full bg-indigo-500 transition-all" style={{ width: `${Math.max((stage.count / maxFunnel) * 100, stage.count ? 4 : 0)}%` }} /></div>
              </div>
            ))}
          </div>
          {dashboard.funnel.every((stage) => stage.count === 0) && <p className="mt-5 text-sm text-slate-500">还没有漏斗数据。先导入职位或创建投递计划。</p>}
        </div>

        <div className="panel">
          <div className="flex items-end justify-between gap-4"><div><p className="eyebrow">投递状态</p><h2 className="mt-2 text-xl font-semibold">状态分布</h2></div><Link className="text-sm font-medium text-indigo-700" href="/campaigns">投递计划 →</Link></div>
          {dashboard.application_status.length === 0 ? <p className="mt-7 text-sm text-slate-500">暂无 Application。</p> : <div className="mt-5 space-y-3">{dashboard.application_status.map((item) => <div className="flex items-center justify-between rounded-xl bg-slate-50 px-4 py-3 text-sm" key={item.status}><span>{statusLabels[item.status] ?? item.status}</span><span className="font-semibold text-slate-900">{item.count}</span></div>)}</div>}
        </div>
      </section>

      <section className="grid gap-6 lg:grid-cols-2">
        <div className="panel">
          <div className="flex items-end justify-between gap-4"><div><p className="eyebrow">Agent Trace</p><h2 className="mt-2 text-xl font-semibold">运行质量</h2></div><Link className="text-sm font-medium text-indigo-700" href="/agent-runs">打开 Trace →</Link></div>
          <div className="mt-6 grid grid-cols-2 gap-3 sm:grid-cols-4">{[["总 Runs", agent.total_runs], ["进行中", agent.active_runs], ["已完成", agent.completed_runs], ["失败/超时", agent.failed_runs]].map(([label, value]) => <div className="rounded-xl bg-slate-50 p-4" key={String(label)}><p className="text-xs text-slate-500">{label}</p><p className="mt-2 text-2xl font-semibold">{value}</p></div>)}</div>
          <div className="mt-5 flex flex-wrap gap-3 text-sm text-slate-500"><span>步骤 {agent.total_steps}</span><span>失败步骤 {agent.failed_steps}</span><span>重试 {agent.retry_count}</span><span>平均延迟 {agent.average_latency_ms.toFixed(1)} ms</span></div>
        </div>
        <div className="panel">
          <div className="flex items-end justify-between gap-4"><div><p className="eyebrow">LLM Cost & Token Usage</p><h2 className="mt-2 text-xl font-semibold">模型用量</h2></div><Link className="text-sm font-medium text-indigo-700" href="/ranking">Ranking →</Link></div>
          <div className="mt-6 grid grid-cols-2 gap-3"><div className="rounded-xl bg-indigo-50 p-4"><p className="text-xs text-indigo-700">Total Tokens</p><p className="mt-2 text-2xl font-semibold text-indigo-950">{usage.total_tokens.toLocaleString()}</p></div><div className="rounded-xl bg-emerald-50 p-4"><p className="text-xs text-emerald-700">Cost</p><p className="mt-2 text-2xl font-semibold text-emerald-950">{formatCost(usage.cost_usd)}</p></div></div>
          <div className="mt-5 space-y-2 text-sm text-slate-500"><p>Prompt {usage.prompt_tokens.toLocaleString()} · Completion {usage.completion_tokens.toLocaleString()}</p><p>来源：{usage.source === "not_recorded" ? "尚无可用用量记录" : `${usage.source}（当前为本地估算）`}</p></div>
        </div>
      </section>
    </div>
  );
}
