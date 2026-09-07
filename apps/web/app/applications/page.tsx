"use client";

import Link from "next/link";
import { useEffect, useState } from "react";

import { getApplications, getCampaigns, type ApplicationListItem, type Campaign } from "../../lib/api";
import { formatJobCollectionTime, isJobFreshForAutoDelivery } from "../../lib/job-freshness";

const statusLabels: Record<string, string> = {
  WAITING_APPROVAL: "等待确认",
  APPROVED: "已批准",
  QUEUED: "已排队",
  EXECUTING: "执行中",
  SUBMITTED: "已投递",
  MANUAL_REQUIRED: "需手动投递",
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

const attentionStatuses = ["CAPTCHA_REQUIRED", "LOGIN_REQUIRED", "PLATFORM_LIMIT", "DOM_CHANGED", "RISK_CONTROL", "UNKNOWN_STATE", "MANUAL_REQUIRED", "FAILED"];
const activeStatuses = ["DISCOVERED", "ANALYZED", "QUALIFIED", "WAITING_APPROVAL", "APPROVED", "QUEUED", "EXECUTING", "PAUSED", ...attentionStatuses];

export default function ApplicationsPage() {
  const [applications, setApplications] = useState<ApplicationListItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [status, setStatus] = useState("active");
  const [platform, setPlatform] = useState("");
  const [campaignId, setCampaignId] = useState("");
  const [campaigns, setCampaigns] = useState<Campaign[]>([]);
  const [page, setPage] = useState(1);
  const [jumpPage, setJumpPage] = useState("");
  const [total, setTotal] = useState(0);
  const [statusCounts, setStatusCounts] = useState<Record<string, number>>({});
  const [refresh, setRefresh] = useState(0);
  const pageCount = Math.max(1, Math.ceil(total / 20));

  useEffect(() => {
    getCampaigns().then((response) => setCampaigns(response.items)).catch(() => {});
  }, []);

  useEffect(() => {
    let current = true;
    setLoading(true);
    setError(null);
    getApplications({ page, page_size: 20, campaign_id: campaignId, platform,
      statuses: status === "active" ? activeStatuses : status === "attention" ? attentionStatuses : status === "all" ? undefined : [status],
    }).then((response) => {
      if (!current) return;
      setApplications(response.items);
      setTotal(response.total);
      setStatusCounts(response.status_counts ?? {});
      setPage((value) => Math.min(value, Math.max(1, Math.ceil(response.total / 20))));
    }).catch((reason) => {
      if (current) setError(reason instanceof Error ? reason.message : "无法加载投递状态。");
    }).finally(() => { if (current) setLoading(false); });
    return () => { current = false; };
  }, [page, status, platform, campaignId, refresh]);

  const countStatuses = (values: string[]) => values.reduce((sum, value) => sum + (statusCounts[value] ?? 0), 0);
  const counts = {
    waiting: statusCounts.WAITING_APPROVAL ?? 0,
    queued: countStatuses(["QUEUED", "EXECUTING", "PAUSED"]),
    submitted: statusCounts.SUBMITTED ?? 0,
    attention: countStatuses(attentionStatuses),
  };

  return (
    <div className="mx-auto max-w-7xl space-y-8">
      <header>
        <p className="eyebrow">我的求职</p>
        <h1 className="mt-3 text-3xl font-semibold tracking-tight">投递追踪</h1>
        <p className="mt-3 max-w-3xl text-slate-500">优先处理进行中的投递；已投递与已取消记录保留在筛选中。下方统计覆盖所选平台和计划的全部记录，不受分页影响。</p>
      </header>

      {error && <div role="alert" className="rounded-xl border border-rose-200 bg-rose-50 p-4 text-rose-800">{error}<button className="ml-3 underline" onClick={() => setRefresh((value) => value + 1)} type="button">重试</button></div>}

      <section className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
        {[["等待确认", counts.waiting], ["队列中", counts.queued], ["已投递", counts.submitted], ["需要处理", counts.attention]].map(([label, value]) => (
          <div className="panel" key={String(label)}><p className="text-sm text-slate-500">{label}</p><p className="mt-3 text-3xl font-semibold">{value}</p></div>
        ))}
      </section>

      <section className="panel overflow-hidden p-0">
        <div className="flex flex-wrap gap-4 border-b border-slate-200 px-6 py-5">
          <label className="text-sm text-slate-600">状态<select className="ml-2 rounded-lg border border-slate-200 bg-white p-2" value={status} onChange={(event) => { setStatus(event.target.value); setPage(1); }}><option value="active">进行中（默认）</option><option value="attention">需要处理</option><option value="all">全部历史</option>{Object.entries(statusLabels).map(([value, label]) => <option key={value} value={value}>{label}</option>)}</select></label>
          <label className="text-sm text-slate-600">平台<select className="ml-2 rounded-lg border border-slate-200 bg-white p-2" value={platform} onChange={(event) => { setPlatform(event.target.value); setPage(1); }}><option value="">全部平台</option><option value="boss">BOSS 直聘</option><option value="zhaopin">智联招聘</option></select></label>
          <label className="text-sm text-slate-600">计划<select className="ml-2 max-w-64 rounded-lg border border-slate-200 bg-white p-2" value={campaignId} onChange={(event) => { setCampaignId(event.target.value); setPage(1); }}><option value="">全部计划</option>{campaigns.map((item) => <option key={item.id} value={item.id}>{item.name}</option>)}</select></label>
        </div>
        {loading ? <div aria-busy="true" className="px-6 py-12 text-center text-slate-500">加载中…</div> : error ? null : applications.length === 0 ? <div className="px-6 py-12 text-center text-slate-500">当前条件下没有投递记录。可以切换到全部历史，或前往投递计划确认岗位。</div> : (
          <div className="overflow-x-auto">
            <table className="w-full min-w-[860px] text-left text-sm">
              <thead className="bg-slate-50 text-slate-500"><tr><th className="px-6 py-4 font-medium">职位</th><th className="px-6 py-4 font-medium">投递计划</th><th className="px-6 py-4 font-medium">平台</th><th className="px-6 py-4 font-medium">状态</th><th className="px-6 py-4 font-medium">更新时间</th><th className="px-6 py-4 font-medium">历史</th></tr></thead>
              <tbody className="divide-y divide-slate-100">
                {applications.map((application) => {
                  const history = application.metadata.state_history ?? [];
                  const needsAttention = ["CAPTCHA_REQUIRED", "LOGIN_REQUIRED", "PLATFORM_LIMIT", "DOM_CHANGED", "RISK_CONTROL", "UNKNOWN_STATE", "FAILED"].includes(application.status);
                  const staleQueued = application.status === "QUEUED" && !isJobFreshForAutoDelivery(application.job);
                  return <tr key={application.id}><td className="px-6 py-4"><Link className="font-semibold text-indigo-700" href={`/jobs/${application.job_id}`}>{application.job.title}</Link><p className="mt-1 text-xs text-slate-500">{application.job.location ?? "地点未注明"}</p>{staleQueued && <p className="mt-2 text-xs font-medium text-amber-700">采集已过期，不会自动投递 · {formatJobCollectionTime(application.job)}</p>}</td><td className="px-6 py-4"><Link className="text-slate-700 hover:text-indigo-700" href={`/campaigns/${application.campaign_id}`}>{application.campaign_name}</Link></td><td className="px-6 py-4 text-slate-500">{application.platform}</td><td className="px-6 py-4"><span className={`rounded-full px-3 py-1 text-xs font-medium ${needsAttention ? "bg-rose-50 text-rose-700" : staleQueued ? "bg-amber-50 text-amber-700" : "bg-indigo-50 text-indigo-700"}`}>{staleQueued ? "等待重新采集" : statusLabels[application.status] ?? application.status}</span>{application.failure_reason && <p className="mt-2 max-w-xs text-xs text-rose-600">{application.failure_reason}</p>}</td><td className="px-6 py-4 text-slate-500">{new Date(application.updated_at).toLocaleString("zh-CN")}</td><td className="px-6 py-4"><details><summary className="cursor-pointer text-xs font-medium text-slate-600">{history.length} 个事件</summary><ol className="mt-3 space-y-2 text-xs text-slate-500">{history.map((event, index) => <li key={`${event.at}-${index}`}>{event.from ?? "—"} → <span className="font-medium text-slate-700">{event.to}</span></li>)}</ol></details></td></tr>;
                })}
              </tbody>
            </table>
          </div>
        )}
        <form className="flex flex-wrap items-center justify-end gap-3 border-t border-slate-200 px-6 py-4 text-sm text-slate-600" onSubmit={(event) => { event.preventDefault(); const target = Number(jumpPage); if (Number.isInteger(target) && target >= 1 && target <= pageCount) { setPage(target); setJumpPage(""); } }}>
          <span>共 {total} 条 · 第 {page}/{pageCount} 页</span>
          <button className="rounded-lg border border-slate-200 px-3 py-2 disabled:opacity-40" disabled={loading || page <= 1} onClick={() => setPage((value) => value - 1)} type="button">上一页</button>
          <button className="rounded-lg border border-slate-200 px-3 py-2 disabled:opacity-40" disabled={loading || page >= pageCount} onClick={() => setPage((value) => value + 1)} type="button">下一页</button>
          <input aria-label="跳转页码" className="w-20 rounded-lg border border-slate-200 bg-white p-2" min={1} max={pageCount} type="number" value={jumpPage} onChange={(event) => setJumpPage(event.target.value)} />
          <button className="rounded-lg border border-slate-200 px-3 py-2 disabled:opacity-40" disabled={loading || !jumpPage} type="submit">跳转</button>
        </form>
      </section>
    </div>
  );
}
