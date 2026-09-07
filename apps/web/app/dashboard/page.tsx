"use client";

import Link from "next/link";
import { useEffect, useState } from "react";

import { StatCard } from "../../components/stat-card";
import { getDashboard, type DashboardResponse } from "../../lib/api";
import { developerMode } from "../../lib/workspaces";

const statusLabels: Record<string, string> = {
  WAITING_APPROVAL: "等待确认",
  APPROVED: "已批准",
  QUEUED: "已排队",
  EXECUTING: "执行中",
  SUBMITTED: "已投递",
  MANUAL_REQUIRED: "需手动投递",
  PAUSED: "已暂停",
  CAPTCHA_REQUIRED: "需要验证码",
  LOGIN_REQUIRED: "需要登录",
  PLATFORM_LIMIT: "平台限制",
  DOM_CHANGED: "页面变化",
  RISK_CONTROL: "风控暂停",
  UNKNOWN_STATE: "未知页面",
  FAILED: "失败",
  CANCELLED: "已取消",
};

function formatCost(cost: number | null) {
  return cost === null ? "费用未知" : `$${cost.toFixed(4)}`;
}

export default function DashboardPage() {
  const [dashboard, setDashboard] = useState<DashboardResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  function loadDashboard() {
    setLoading(true);
    setError(null);
    getDashboard()
      .then(setDashboard)
      .catch((reason) => setError(reason instanceof Error ? reason.message : "工作台加载失败。"))
      .finally(() => setLoading(false));
  }

  useEffect(() => {
    loadDashboard();
  }, []);

  if (loading) {
    return <div className="mx-auto max-w-7xl space-y-6" aria-busy="true">
      <div className="h-32 animate-pulse rounded-2xl bg-slate-100" />
      <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">{[1, 2, 3, 4].map((item) => <div className="h-28 animate-pulse rounded-2xl bg-slate-100" key={item} />)}</div>
      <div className="panel text-center text-slate-500">正在加载工作台…</div>
    </div>;
  }

  if (!dashboard) {
    return <div className="panel mx-auto flex max-w-2xl flex-col items-center text-center" role="alert">
      <p className="text-sm font-semibold text-rose-700">工作台暂时无法加载</p>
      <p className="mt-2 text-sm leading-6 text-slate-500">{error ?? "请稍后重试。"}</p>
      <button className="mt-5 rounded-xl bg-indigo-600 px-4 py-2.5 text-sm font-medium text-white transition hover:bg-indigo-700" onClick={loadDashboard} type="button">重新加载</button>
    </div>;
  }

  const { summary, agent, token_usage: usage } = dashboard;
  const maxFunnel = Math.max(...dashboard.funnel.map((stage) => stage.count), 1);
  const cancelledCount = dashboard.application_status.find((item) => item.status === "CANCELLED")?.count ?? 0;
  const visibleApplicationStatus = dashboard.application_status.filter((item) => item.status !== "CANCELLED");

  return (
    <div className="mx-auto max-w-7xl space-y-8">
      <header className="flex flex-wrap items-end justify-between gap-5">
        <div>
          <p className="eyebrow">CareerPilot / Product Dashboard</p>
          <h1 className="mt-3 text-3xl font-semibold tracking-tight sm:text-4xl">求职工作台</h1>
          <p className="mt-3 max-w-3xl text-slate-500">集中查看今天需要处理的岗位、投递计划和职业成长建议。</p>
        </div>
        <p className="text-xs text-slate-400">刷新于 {new Date(dashboard.refreshed_at).toLocaleString("zh-CN")}</p>
      </header>

      {error && <div className="flex flex-wrap items-center justify-between gap-3 rounded-xl border border-amber-200 bg-amber-50 p-4 text-sm text-amber-800"><span>{error}</span><button className="font-medium underline underline-offset-2" onClick={loadDashboard} type="button">重新加载</button></div>}

      <section className="panel cp-action-surface border-indigo-200">
        <div className="flex flex-wrap items-center justify-between gap-4">
          <div>
            <p className="eyebrow">下一步</p>
            <h2 className="mt-2 text-xl font-semibold">今天先完成一件求职任务</h2>
            <p className="mt-2 text-sm leading-6 text-slate-600">从岗位搜索、人工确认或投递进度开始，系统会保留你的采集和计划状态。</p>
          </div>
          <Link className="rounded-xl bg-indigo-600 px-5 py-3 text-sm font-medium text-white transition hover:bg-indigo-700" href={summary.attention_required > 0 ? "/delivery" : summary.jobs_total === 0 ? "/browser-tasks" : "/campaigns"}>
            {summary.attention_required > 0 ? "处理待办" : summary.jobs_total === 0 ? "开始找职位" : "查看投递计划"}
          </Link>
        </div>
      </section>

      <section className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
        <Link href="/jobs"><StatCard label="已保存职位" value={summary.jobs_total} hint="进入职位库继续筛选" /></Link>
        <Link href="/campaigns"><StatCard label="投递计划" value={summary.campaigns_total} hint="确认岗位、入队和执行" /></Link>
        <Link href="/applications"><StatCard label="累计已投递" value={summary.submitted_applications} hint="按投递记录计数，不代表获得回复" /></Link>
        <StatCard label="需要处理" value={summary.attention_required} hint="验证码、风控、错误或未知页面" />
      </section>

      <section className="grid gap-6 xl:grid-cols-[1.5fr_1fr]">
        <div className="panel">
          <div className="flex flex-wrap items-end justify-between gap-4"><div><p className="eyebrow">当前概况</p><h2 className="mt-2 text-xl font-semibold">岗位与投递数量</h2></div><Link className="text-sm font-medium text-indigo-700" href="/applications">查看投递状态 →</Link></div>
          <p className="mt-3 text-xs leading-5 text-slate-500">职位库与投递状态采用不同统计口径，不构成转化漏斗。高匹配指所有简历历史评分曾达 70 分的去重岗位。</p>
          <div className="mt-7 space-y-4">
            {dashboard.funnel.map((stage) => (
              <div key={stage.key}>
                <div className="mb-1 flex items-center justify-between gap-3 text-sm"><span className="font-medium text-slate-700">{stage.label}</span><span className="text-slate-500">{stage.count}</span></div>
                <div className="h-3 overflow-hidden rounded-full bg-slate-100"><div className="h-full rounded-full bg-indigo-500 transition-all" style={{ width: `${Math.max((stage.count / maxFunnel) * 100, stage.count ? 4 : 0)}%` }} /></div>
              </div>
            ))}
          </div>
          {dashboard.funnel.every((stage) => stage.count === 0) && <p className="mt-5 text-sm text-slate-500">还没有求职数据。先导入职位或创建投递计划。</p>}
        </div>

        <div className="panel">
          <div className="flex items-end justify-between gap-4"><div><p className="eyebrow">投递状态</p><h2 className="mt-2 text-xl font-semibold">状态分布</h2></div><Link className="text-sm font-medium text-indigo-700" href="/campaigns">投递计划 →</Link></div>
          {visibleApplicationStatus.length === 0 ? <p className="mt-7 text-sm text-slate-500">暂无进行中或已投递记录。</p> : <div className="mt-5 space-y-3">{visibleApplicationStatus.map((item) => <div className="flex items-center justify-between rounded-xl bg-slate-50 px-4 py-3 text-sm" key={item.status}><span>{statusLabels[item.status] ?? item.status}</span><span className="font-semibold text-slate-900">{item.count}</span></div>)}</div>}
          {cancelledCount > 0 && <Link className="mt-4 block text-xs text-slate-500 hover:text-indigo-700" href="/applications">另有 {cancelledCount} 条已取消历史，可在投递进度中查看 →</Link>}
        </div>
      </section>

      {developerMode && <section className="grid gap-6 lg:grid-cols-2">
        <p className="text-sm text-slate-500 lg:col-span-2">开发诊断：以下仅统计旧版求职计划 Agent 运行记录，不包含职业顾问、岗位报告和独立排名任务；费用未知不代表免费。</p>
        <div className="panel">
          <div className="flex items-end justify-between gap-4"><div><p className="eyebrow">系统详情</p><h2 className="mt-2 text-xl font-semibold">Agent 运行质量</h2></div><Link className="text-sm font-medium text-indigo-700" href="/agent-runs">查看运行记录 →</Link></div>
          <div className="mt-6 grid grid-cols-2 gap-3 sm:grid-cols-4">{[["总 Runs", agent.total_runs], ["进行中", agent.active_runs], ["已完成", agent.completed_runs], ["失败/超时", agent.failed_runs]].map(([label, value]) => <div className="rounded-xl bg-slate-50 p-4" key={String(label)}><p className="text-xs text-slate-500">{label}</p><p className="mt-2 text-2xl font-semibold">{value}</p></div>)}</div>
          <div className="mt-5 flex flex-wrap gap-3 text-sm text-slate-500"><span>步骤 {agent.total_steps}</span><span>失败步骤 {agent.failed_steps}</span><span>重试 {agent.retry_count}</span><span>平均延迟 {agent.average_latency_ms.toFixed(1)} ms</span></div>
        </div>
        <div className="panel">
          <div className="flex items-end justify-between gap-4"><div><p className="eyebrow">系统详情</p><h2 className="mt-2 text-xl font-semibold">模型用量</h2></div><Link className="text-sm font-medium text-indigo-700" href="/settings">模型设置 →</Link></div>
          <div className="mt-6 grid grid-cols-2 gap-3"><div className="rounded-xl bg-indigo-50 p-4"><p className="text-xs text-indigo-700">Total Tokens</p><p className="mt-2 text-2xl font-semibold text-indigo-950">{usage.total_tokens.toLocaleString()}</p></div><div className="rounded-xl bg-emerald-50 p-4"><p className="text-xs text-emerald-700">Cost</p><p className="mt-2 text-2xl font-semibold text-emerald-950">{formatCost(usage.cost_usd)}</p></div></div>
          <div className="mt-5 space-y-2 text-sm text-slate-500"><p>Prompt {usage.prompt_tokens.toLocaleString()} · Completion {usage.completion_tokens.toLocaleString()}</p><p>来源：{usage.source === "not_recorded" ? "尚无可用用量记录" : `${usage.source}（当前为本地估算）`}</p></div>
        </div>
      </section>}
    </div>
  );
}
