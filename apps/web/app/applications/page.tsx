"use client";

import Link from "next/link";
import { useEffect, useMemo, useState } from "react";

import { getApplications, type ApplicationListItem } from "../../lib/api";

const statusLabels: Record<string, string> = {
  WAITING_APPROVAL: "等待确认",
  APPROVED: "已批准",
  QUEUED: "已排队",
  EXECUTING: "执行中",
  SUBMITTED: "已投递",
  PAUSED: "已暂停",
  CANCELLED: "已取消",
  CAPTCHA_REQUIRED: "需要验证码",
  LOGIN_REQUIRED: "需要登录",
  PLATFORM_LIMIT: "平台限制",
  DOM_CHANGED: "页面变化",
  RISK_CONTROL: "风控暂停",
  UNKNOWN_STATE: "未知页面",
  FAILED: "失败",
};

export default function ApplicationsPage() {
  const [applications, setApplications] = useState<ApplicationListItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    getApplications()
      .then((response) => setApplications(response.items))
      .catch(() => setError("无法加载投递状态。"))
      .finally(() => setLoading(false));
  }, []);

  const counts = useMemo(() => ({
    waiting: applications.filter((item) => item.status === "WAITING_APPROVAL").length,
    queued: applications.filter((item) => ["QUEUED", "EXECUTING", "PAUSED"].includes(item.status)).length,
    submitted: applications.filter((item) => item.status === "SUBMITTED").length,
    attention: applications.filter((item) => ["CAPTCHA_REQUIRED", "LOGIN_REQUIRED", "PLATFORM_LIMIT", "DOM_CHANGED", "RISK_CONTROL", "UNKNOWN_STATE", "FAILED"].includes(item.status)).length,
  }), [applications]);

  return (
    <div className="mx-auto max-w-7xl space-y-8">
      <header>
        <p className="eyebrow">Application State Machine</p>
        <h1 className="mt-3 text-3xl font-semibold tracking-tight">投递追踪</h1>
        <p className="mt-3 max-w-3xl text-slate-500">每个职位都有独立、可审计的状态历史；遇到登录、验证码、风控或未知页面时会暂停等待你处理。</p>
      </header>

      {error && <div className="rounded-xl border border-rose-200 bg-rose-50 p-4 text-rose-800">{error}</div>}

      <section className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
        {[["等待确认", counts.waiting], ["队列中", counts.queued], ["已投递", counts.submitted], ["需要处理", counts.attention]].map(([label, value]) => (
          <div className="panel" key={String(label)}><p className="text-sm text-slate-500">{label}</p><p className="mt-3 text-3xl font-semibold">{value}</p></div>
        ))}
      </section>

      <section className="panel overflow-hidden p-0">
        <div className="border-b border-slate-200 px-6 py-5"><p className="eyebrow">Applications</p><h2 className="mt-2 text-xl font-semibold">状态列表</h2></div>
        {loading ? <div className="px-6 py-12 text-center text-slate-500">加载中…</div> : applications.length === 0 ? <div className="px-6 py-12 text-center text-slate-500">还没有投递记录。请先启动投递计划并批准职位。</div> : (
          <div className="overflow-x-auto">
            <table className="w-full min-w-[860px] text-left text-sm">
              <thead className="bg-slate-50 text-slate-500"><tr><th className="px-6 py-4 font-medium">职位</th><th className="px-6 py-4 font-medium">投递计划</th><th className="px-6 py-4 font-medium">平台</th><th className="px-6 py-4 font-medium">状态</th><th className="px-6 py-4 font-medium">更新时间</th><th className="px-6 py-4 font-medium">历史</th></tr></thead>
              <tbody className="divide-y divide-slate-100">
                {applications.map((application) => {
                  const history = application.metadata.state_history ?? [];
                  const needsAttention = ["CAPTCHA_REQUIRED", "LOGIN_REQUIRED", "PLATFORM_LIMIT", "DOM_CHANGED", "RISK_CONTROL", "UNKNOWN_STATE", "FAILED"].includes(application.status);
                  return <tr key={application.id}><td className="px-6 py-4"><Link className="font-semibold text-indigo-700" href={`/jobs/${application.job_id}`}>{application.job.title}</Link><p className="mt-1 text-xs text-slate-500">{application.job.location ?? "地点未注明"}</p></td><td className="px-6 py-4"><Link className="text-slate-700 hover:text-indigo-700" href={`/campaigns/${application.campaign_id}`}>{application.campaign_name}</Link></td><td className="px-6 py-4 text-slate-500">{application.platform}</td><td className="px-6 py-4"><span className={`rounded-full px-3 py-1 text-xs font-medium ${needsAttention ? "bg-rose-50 text-rose-700" : "bg-indigo-50 text-indigo-700"}`}>{statusLabels[application.status] ?? application.status}</span>{application.failure_reason && <p className="mt-2 max-w-xs text-xs text-rose-600">{application.failure_reason}</p>}</td><td className="px-6 py-4 text-slate-500">{new Date(application.updated_at).toLocaleString("zh-CN")}</td><td className="px-6 py-4"><details><summary className="cursor-pointer text-xs font-medium text-slate-600">{history.length} 个事件</summary><ol className="mt-3 space-y-2 text-xs text-slate-500">{history.map((event, index) => <li key={`${event.at}-${index}`}>{event.from ?? "—"} → <span className="font-medium text-slate-700">{event.to}</span></li>)}</ol></details></td></tr>;
                })}
              </tbody>
            </table>
          </div>
        )}
      </section>
    </div>
  );
}
