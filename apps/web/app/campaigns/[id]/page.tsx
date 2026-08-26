"use client";

import Link from "next/link";
import { useParams } from "next/navigation";
import { useEffect, useMemo, useState } from "react";

import {
  approveCampaignJobs,
  campaignAction,
  getCampaign,
  type CampaignDetail,
} from "../../../lib/api";

const statusLabels: Record<string, string> = {
  DRAFT: "草稿",
  RANKING: "排名中",
  WAITING_APPROVAL: "等待确认",
  RUNNING: "运行中",
  PAUSED: "已暂停",
  COMPLETED: "已完成",
  CANCELLED: "已取消",
  FAILED: "失败",
  APPROVED: "已批准",
  QUEUED: "已排队",
  EXECUTING: "执行中",
  SUBMITTED: "已投递",
  CAPTCHA_REQUIRED: "需要验证码",
  LOGIN_REQUIRED: "需要登录",
  PLATFORM_LIMIT: "平台限制",
  DOM_CHANGED: "页面变化",
  RISK_CONTROL: "风控暂停",
  UNKNOWN_STATE: "未知页面",
};

export default function CampaignDetailPage() {
  const params = useParams<{ id: string }>();
  const campaignId = params.id;
  const [campaign, setCampaign] = useState<CampaignDetail | null>(null);
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [loading, setLoading] = useState(true);
  const [actionLoading, setActionLoading] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    getCampaign(campaignId)
      .then(setCampaign)
      .catch((reason) => setError(reason instanceof Error ? reason.message : "Campaign 加载失败。"))
      .finally(() => setLoading(false));
  }, [campaignId]);

  const waitingJobIds = useMemo(
    () => campaign?.candidate_jobs.filter((item) => item.status === "WAITING_APPROVAL").map((item) => item.job_id) ?? [],
    [campaign],
  );

  async function runAction(action: "start" | "pause" | "resume" | "cancel") {
    if (!campaign) return;
    if (action === "cancel" && !window.confirm("确认取消这个投递计划吗？取消后不能继续执行。")) return;
    setActionLoading(action);
    setError(null);
    try {
      setCampaign(await campaignAction(campaign.id, action));
      setSelected(new Set());
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Campaign 操作失败。");
    } finally {
      setActionLoading(null);
    }
  }

  async function approveSelected() {
    if (!campaign || selected.size === 0) return;
    setActionLoading("approve");
    setError(null);
    try {
      setCampaign(await approveCampaignJobs(campaign.id, [...selected]));
      setSelected(new Set());
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "批量批准失败。");
    } finally {
      setActionLoading(null);
    }
  }

  function toggleJob(jobId: string) {
    setSelected((current) => {
      const next = new Set(current);
      if (next.has(jobId)) next.delete(jobId);
      else next.add(jobId);
      return next;
    });
  }

  function toggleAll() {
    setSelected((current) => current.size === waitingJobIds.length ? new Set() : new Set(waitingJobIds));
  }

  if (loading) return <div className="panel mx-auto max-w-6xl text-center text-slate-500">加载 Campaign…</div>;
  if (!campaign) return <div className="panel mx-auto max-w-6xl text-rose-700">{error ?? "Campaign 不存在。"}</div>;

  const canPause = ["WAITING_APPROVAL", "RUNNING"].includes(campaign.status);
  const canCancel = !["COMPLETED", "CANCELLED"].includes(campaign.status);

  return (
    <div className="mx-auto max-w-7xl space-y-8">
      <header className="flex flex-wrap items-end justify-between gap-5">
        <div>
          <Link className="text-sm font-medium text-indigo-700" href="/campaigns">← 返回投递计划</Link>
          <p className="eyebrow mt-5">投递计划详情</p>
          <h1 className="mt-3 text-3xl font-semibold tracking-tight">{campaign.name}</h1>
          <p className="mt-3 text-slate-500">最低 {campaign.min_score} 分 · 最多 {campaign.max_jobs} 个职位 · {campaign.target_cities.join("、") || "不限城市"}</p>
        </div>
        <div className="flex flex-wrap gap-2">
          {campaign.status === "DRAFT" && <button className="rounded-xl bg-indigo-600 px-5 py-2.5 text-sm font-medium text-white disabled:opacity-50" disabled={actionLoading !== null} onClick={() => void runAction("start")} type="button">{actionLoading === "start" ? "搜索并排名中…" : "启动计划"}</button>}
          {canPause && <button className="rounded-xl border border-amber-200 px-5 py-2.5 text-sm font-medium text-amber-700 disabled:opacity-50" disabled={actionLoading !== null} onClick={() => void runAction("pause")} type="button">暂停</button>}
          {campaign.status === "PAUSED" && <button className="rounded-xl bg-emerald-600 px-5 py-2.5 text-sm font-medium text-white disabled:opacity-50" disabled={actionLoading !== null} onClick={() => void runAction("resume")} type="button">继续</button>}
          {canCancel && <button className="rounded-xl border border-rose-200 px-5 py-2.5 text-sm font-medium text-rose-700 disabled:opacity-50" disabled={actionLoading !== null} onClick={() => void runAction("cancel")} type="button">取消计划</button>}
        </div>
      </header>

      {error && <div className="rounded-xl border border-rose-200 bg-rose-50 p-4 text-rose-800">{error}</div>}

      <section className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
        <div className="panel"><p className="text-xs text-slate-400">计划状态</p><p className="mt-2 text-xl font-semibold text-indigo-700">{statusLabels[campaign.status] ?? campaign.status}</p></div>
        <div className="panel"><p className="text-xs text-slate-400">候选职位</p><p className="mt-2 text-2xl font-semibold">{campaign.candidate_count}</p></div>
        <div className="panel"><p className="text-xs text-slate-400">等待确认</p><p className="mt-2 text-2xl font-semibold">{campaign.waiting_approval_count}</p></div>
        <div className="panel"><p className="text-xs text-slate-400">队列中</p><p className="mt-2 text-2xl font-semibold">{campaign.queued_count}</p></div>
      </section>

      {campaign.status === "DRAFT" && (
        <section className="rounded-2xl border border-indigo-100 bg-indigo-50 p-6">
          <p className="font-semibold text-indigo-900">准备启动</p>
          <p className="mt-2 text-sm leading-6 text-indigo-700">启动后将搜索符合关键词和城市条件的职位并完成智能排名，随后停在“等待确认”，不会未经批准直接投递。</p>
        </section>
      )}

      <section className="panel overflow-hidden p-0">
        <div className="flex flex-wrap items-center justify-between gap-4 border-b border-slate-200 px-6 py-5">
          <div><p className="eyebrow">候选职位</p><h2 className="mt-2 text-xl font-semibold">智能排名与人工确认</h2></div>
          <button className="rounded-xl bg-indigo-600 px-5 py-2.5 text-sm font-medium text-white disabled:cursor-not-allowed disabled:opacity-50" disabled={selected.size === 0 || actionLoading !== null || campaign.status === "PAUSED"} onClick={() => void approveSelected()} type="button">
            {actionLoading === "approve" ? "正在批准并排队…" : `批准并加入队列 (${selected.size})`}
          </button>
        </div>
        {campaign.candidate_jobs.length === 0 ? (
          <div className="px-6 py-12 text-center text-slate-500">{campaign.status === "DRAFT" ? "启动后将在这里展示排名结果。" : "当前筛选条件下没有达到阈值的职位。"}</div>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full min-w-[900px] text-left text-sm">
              <thead className="bg-slate-50 text-slate-500"><tr><th className="px-5 py-4"><input aria-label="选择全部待确认职位" checked={waitingJobIds.length > 0 && selected.size === waitingJobIds.length} onChange={toggleAll} type="checkbox" /></th><th className="px-5 py-4 font-medium">排名</th><th className="px-5 py-4 font-medium">职位</th><th className="px-5 py-4 font-medium">分数</th><th className="px-5 py-4 font-medium">状态</th><th className="px-5 py-4 font-medium">State Trace</th></tr></thead>
              <tbody className="divide-y divide-slate-100">
                {campaign.candidate_jobs.map((item) => {
                  const waiting = item.status === "WAITING_APPROVAL";
                  const history = item.application?.metadata.state_history ?? [];
                  return (
                    <tr className="align-top" key={item.id}>
                      <td className="px-5 py-4"><input aria-label={`选择 ${item.job.title}`} checked={selected.has(item.job_id)} disabled={!waiting || campaign.status === "PAUSED"} onChange={() => toggleJob(item.job_id)} type="checkbox" /></td>
                      <td className="px-5 py-4 font-semibold">#{item.rank}</td>
                      <td className="px-5 py-4"><Link className="font-semibold text-indigo-700" href={`/jobs/${item.job_id}`}>{item.job.title}</Link><p className="mt-1 text-xs text-slate-500">{item.job.location ?? "地点未注明"} · {item.job.platform}</p></td>
                      <td className="px-5 py-4 text-lg font-semibold">{item.score.toFixed(1)}</td>
                      <td className="px-5 py-4"><span className={`rounded-full px-3 py-1 text-xs font-medium ${waiting ? "bg-amber-50 text-amber-700" : "bg-indigo-50 text-indigo-700"}`}>{statusLabels[item.status] ?? item.status}</span></td>
                      <td className="px-5 py-4">
                        <details><summary className="cursor-pointer text-xs font-medium text-slate-600">{history.length} 个状态事件</summary><ol className="mt-3 space-y-2 text-xs text-slate-500">{history.map((event, index) => <li key={`${event.at}-${index}`}><span className="font-medium text-slate-700">{event.to}</span> · {event.event}</li>)}</ol></details>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}
      </section>
    </div>
  );
}
