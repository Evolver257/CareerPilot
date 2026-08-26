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

const rankingStageLabels: Record<string, string> = {
  queued: "等待执行",
  recovering: "正在恢复",
  loading_candidates: "加载候选职位",
  rule_filter: "规则筛选",
  embedding_rank: "语义召回",
  reranker: "综合重排",
  llm_judge: "LLM 深度评分",
  deterministic_rank: "快速综合评分",
  final_ranking: "生成最终排名",
  completed: "排名完成",
  failed: "排名失败",
  timed_out: "执行超时",
  cancelled: "已取消",
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

  useEffect(() => {
    if (campaign?.status !== "RANKING") return;
    const timer = window.setInterval(() => {
      getCampaign(campaignId)
        .then((next) => {
          setCampaign(next);
          setError(null);
        })
        .catch((reason) => setError(reason instanceof Error ? reason.message : "排名进度刷新失败。"));
    }, 1500);
    return () => window.clearInterval(timer);
  }, [campaign?.status, campaignId]);

  const waitingJobIds = useMemo(
    () => campaign?.candidate_jobs.filter((item) => item.status === "WAITING_APPROVAL").map((item) => item.job_id) ?? [],
    [campaign],
  );

  async function runAction(action: "start" | "retry" | "pause" | "resume" | "cancel") {
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
  const canApprove = ["WAITING_APPROVAL", "RUNNING"].includes(campaign.status);
  const rankingRun = campaign.ranking_run;

  return (
    <div className="mx-auto max-w-7xl space-y-8">
      <header className="flex flex-wrap items-end justify-between gap-5">
        <div>
          <Link className="text-sm font-medium text-indigo-700" href="/campaigns">← 返回投递计划</Link>
          <p className="eyebrow mt-5">投递计划详情</p>
          <h1 className="mt-3 text-3xl font-semibold tracking-tight">{campaign.name}</h1>
          <p className="mt-3 text-slate-500">最低 {campaign.min_score} 分 · 最多 {campaign.max_jobs} 个职位 · {campaign.scoring_mode === "llm" ? "LLM 深度评分" : "快速评分"} · {campaign.target_cities.join("、") || "不限城市"}</p>
        </div>
        <div className="flex flex-wrap gap-2">
          {campaign.status === "DRAFT" && <button className="rounded-xl bg-indigo-600 px-5 py-2.5 text-sm font-medium text-white disabled:opacity-50" disabled={actionLoading !== null} onClick={() => void runAction("start")} type="button">{actionLoading === "start" ? "搜索并排名中…" : "启动计划"}</button>}
          {campaign.status === "FAILED" && <button className="rounded-xl bg-indigo-600 px-5 py-2.5 text-sm font-medium text-white disabled:opacity-50" disabled={actionLoading !== null} onClick={() => void runAction("retry")} type="button">{actionLoading === "retry" ? "正在重新排队…" : "重试排名"}</button>}
          {canPause && <button className="rounded-xl border border-amber-200 px-5 py-2.5 text-sm font-medium text-amber-700 disabled:opacity-50" disabled={actionLoading !== null} onClick={() => void runAction("pause")} type="button">暂停</button>}
          {campaign.status === "PAUSED" && <button className="rounded-xl bg-emerald-600 px-5 py-2.5 text-sm font-medium text-white disabled:opacity-50" disabled={actionLoading !== null} onClick={() => void runAction("resume")} type="button">继续</button>}
          {canCancel && <button className="rounded-xl border border-rose-200 px-5 py-2.5 text-sm font-medium text-rose-700 disabled:opacity-50" disabled={actionLoading !== null} onClick={() => void runAction("cancel")} type="button">取消计划</button>}
        </div>
      </header>

      {error && <div className="rounded-xl border border-rose-200 bg-rose-50 p-4 text-rose-800">{error}</div>}

      {rankingRun && ["RANKING", "FAILED"].includes(campaign.status) && (
        <section className="panel">
          <div className="flex flex-wrap items-center justify-between gap-3">
            <div>
              <p className="eyebrow">排名任务进度</p>
              <h2 className="mt-2 text-lg font-semibold">{rankingStageLabels[rankingRun.stage] ?? rankingRun.stage}</h2>
            </div>
            <span className="rounded-full bg-indigo-50 px-3 py-1 text-sm font-semibold text-indigo-700">{rankingRun.progress}%</span>
          </div>
          <div aria-label={`排名进度 ${rankingRun.progress}%`} aria-valuemax={100} aria-valuemin={0} aria-valuenow={rankingRun.progress} className="mt-5 h-3 overflow-hidden rounded-full bg-slate-100" role="progressbar">
            <div className="h-full rounded-full bg-gradient-to-r from-indigo-500 to-violet-500 transition-all duration-500" style={{ width: `${rankingRun.progress}%` }} />
          </div>
          <div className="mt-4 grid gap-3 text-sm text-slate-500 sm:grid-cols-4">
            <p>已处理 <span className="font-semibold text-slate-900">{rankingRun.processed_candidates}/{rankingRun.total_candidates || "—"}</span></p>
            <p>缓存命中 <span className="font-semibold text-slate-900">{rankingRun.cache_hits}</span></p>
            <p>LLM 调用 <span className="font-semibold text-slate-900">{rankingRun.llm_calls}</span></p>
            <p>评分模式 <span className="font-semibold text-slate-900">{campaign.scoring_mode === "llm" ? "深度" : "快速"}</span></p>
          </div>
          {rankingRun.error && <p className={`mt-4 rounded-xl p-3 text-sm ${campaign.status === "FAILED" ? "bg-rose-50 text-rose-700" : "bg-amber-50 text-amber-700"}`}>{rankingRun.error}</p>}
          {campaign.status === "RANKING" && <p className="mt-4 text-xs leading-5 text-slate-400">可以离开此页面，排名会在后台继续。已完成的评分和候选职位会逐条保存。</p>}
        </section>
      )}

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
          <button className="rounded-xl bg-indigo-600 px-5 py-2.5 text-sm font-medium text-white disabled:cursor-not-allowed disabled:opacity-50" disabled={selected.size === 0 || actionLoading !== null || !canApprove} onClick={() => void approveSelected()} type="button">
            {actionLoading === "approve" ? "正在批准并排队…" : `批准并加入队列 (${selected.size})`}
          </button>
        </div>
        {campaign.candidate_jobs.length === 0 ? (
          <div className="px-6 py-12 text-center text-slate-500">{campaign.status === "DRAFT" ? "启动后将在这里展示排名结果。" : campaign.status === "RANKING" ? "正在处理候选职位，首个达到阈值的结果会自动出现在这里。" : "当前筛选条件下没有达到阈值的职位。"}</div>
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
                      <td className="px-5 py-4"><input aria-label={`选择 ${item.job.title}`} checked={selected.has(item.job_id)} disabled={!waiting || !canApprove} onChange={() => toggleJob(item.job_id)} type="checkbox" /></td>
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
