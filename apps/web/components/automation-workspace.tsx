"use client";

import Link from "next/link";
import { useCallback, useEffect, useState } from "react";

import { LlmDeepScoreBadge } from "./scoring-mode-badge";
import {
  cancelBrowserTaskCampaign,
  createCampaignBrowserTasks,
  deleteBrowserTaskCampaign,
  getApplications,
  getBrowserTaskCampaigns,
  getCampaigns,
  type ApplicationListItem,
  type BrowserTask,
  type BrowserTaskCampaignGroup,
  type Campaign,
} from "../lib/api";
import { BossPluginWorkflow } from "./boss-plugin-workflow";
import { ZhaopinPluginWorkflow } from "./zhaopin-plugin-workflow";
import { isJobFreshForAutoDelivery } from "../lib/job-freshness";
import { launchDeliveryTasks, type DeliveryTask } from "../lib/delivery-bridge";
import { developerMode } from "../lib/workspaces";

const statusLabels: Record<BrowserTaskCampaignGroup["status"], string> = {
  PENDING: "待启动",
  CONNECTING: "等待 Extension",
  RUNNING: "执行中",
  WAITING_FOR_USER: "等待人工处理",
  COMPLETED: "已完成",
  CANCELLED: "已取消",
  FAILED: "失败",
  PARTIAL: "部分完成",
};

const applicationStatusLabels: Record<string, string> = {
  SUBMITTED: "已投递",
  MANUAL_REQUIRED: "需手动投递",
  QUEUED: "排队中",
  EXECUTING: "执行中",
  FAILED: "失败",
  CANCELLED: "已取消",
};

export default function AutomationWorkspace({ view = "collect", initialCampaignId = "" }: { view?: "collect" | "delivery"; initialCampaignId?: string }) {
  const [searchPlatform, setSearchPlatform] = useState<"boss" | "zhaopin">("boss");
  const [taskGroups, setTaskGroups] = useState<BrowserTaskCampaignGroup[]>([]);
  const [applications, setApplications] = useState<ApplicationListItem[]>([]);
  const [campaigns, setCampaigns] = useState<Campaign[]>([]);
  const [campaignId, setCampaignId] = useState(initialCampaignId);
  const [scenario, setScenario] = useState("SUCCESS");
  const [loading, setLoading] = useState(true);
  const [creating, setCreating] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [maintainingCampaignId, setMaintainingCampaignId] = useState<string | null>(null);
  const [staleQueuedCount, setStaleQueuedCount] = useState(0);

  const load = useCallback(() => {
    if (view === "collect") return Promise.resolve();
    const loadQueued = async () => {
      const result = await getApplications({ statuses: ["QUEUED"], page: 1, page_size: 200 });
      const items = [...result.items];
      for (let page = 2; items.length < result.total; page += 1) {
        const next = await getApplications({ statuses: ["QUEUED"], page, page_size: 200 });
        if (!next.items.length) break;
        items.push(...next.items);
      }
      return { ...result, items: [...new Map(items.map((item) => [item.id, item])).values()] };
    };
    return Promise.all([getBrowserTaskCampaigns(), loadQueued(), getCampaigns()]).then(([taskResponse, applicationResponse, campaignResponse]) => {
      const allQueued = applicationResponse.items.filter((item) => item.status === "QUEUED");
      const queued = allQueued.filter((item) => isJobFreshForAutoDelivery(item.job));
      setTaskGroups(taskResponse.items);
      setApplications(queued);
      setCampaigns(campaignResponse.items);
      setStaleQueuedCount(allQueued.length - queued.length);
      setCampaignId((current) => initialCampaignId || (queued.some((item) => item.campaign_id === current) ? current : queued[0]?.campaign_id ?? ""));
    });
  }, [view, initialCampaignId]);

  async function handleCancelGroup(group: BrowserTaskCampaignGroup) {
    if (!window.confirm(`确定取消投递计划“${group.campaign_name}”中尚未完成的自动化任务吗？`)) return;
    setMaintainingCampaignId(group.campaign_id);
    setError(null);
    try {
      await cancelBrowserTaskCampaign(group.campaign_id);
      setNotice(`已取消“${group.campaign_name}”中尚未完成的自动化任务。`);
      await load();
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "投递任务取消失败。");
    } finally {
      setMaintainingCampaignId(null);
    }
  }

  async function handleDeleteGroup(group: BrowserTaskCampaignGroup) {
    if (!window.confirm(`确定删除“${group.campaign_name}”的自动化任务记录吗？投递计划和 Application 数据会保留。`)) return;
    setMaintainingCampaignId(group.campaign_id);
    setError(null);
    try {
      await deleteBrowserTaskCampaign(group.campaign_id);
      setNotice(`已删除“${group.campaign_name}”的自动化任务记录。`);
      await load();
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "任务记录删除失败。");
    } finally {
      setMaintainingCampaignId(null);
    }
  }

  useEffect(() => {
    load().catch(() => setError("无法加载 Browser Task 数据，请确认 API 服务已启动。")).finally(() => setLoading(false));
  }, [load]);

  async function handleCreate() {
    if (!campaignId || automaticApplications.length === 0) return;
    setCreating(true);
    setError(null);
    setNotice(null);
    try {
      const tasks: DeliveryTask[] = [];
      const failures: string[] = [];
      for (const platform of ["boss", "zhaopin"] as const) {
        if (!automaticApplications.some((item) => item.platform === platform)) continue;
        try {
          // Start only when the extension reaches this job; a missing extension leaves reusable pending tasks.
          const batch = await createCampaignBrowserTasks({ campaign_id: campaignId, platform, scenario, auto_start: false });
          for (const task of batch.items) {
            const url = getTaskLaunchUrl(task);
            if (url && task.platform === platform) tasks.push({ task_id: task.id, url, platform });
            else failures.push(`${platform} 任务缺少有效岗位原页`);
          }
          if (batch.failed_count) failures.push(`${platform}：${batch.failed_count} 个岗位创建失败`);
        } catch (reason) { failures.push(reason instanceof Error ? reason.message : `${platform} 创建失败`); }
      }
      if (tasks.length) {
        const accepted = await launchDeliveryTasks(tasks);
        setNotice(`扩展已接收 ${accepted} 个新任务，其余复用任务如已在队列中将继续执行。使用同一个标签页逐个打开岗位原页，BOSS 点击“立即沟通”，智联点击“立即投递”；确认成功后更新为已投递。遇到验证或结果不明确时暂停。`);
      }
      if (failures.length) setError(failures.join("；"));
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Browser Task 创建失败。");
    } finally {
      await load().catch(() => {});
      setCreating(false);
    }
  }

  const selectedApplications = applications.filter((item) => item.campaign_id === campaignId);
  const automaticApplications = selectedApplications.filter((item) => item.platform === "boss" || item.platform === "zhaopin");
  const manualApplications = selectedApplications.filter((item) => item.platform !== "boss" && item.platform !== "zhaopin");
  const platformSummary = [...new Set(selectedApplications.map((item) => item.platform))].join("、") || "暂无";

  return (
    <div className="mx-auto max-w-7xl space-y-8">
      <header>
        <p className="eyebrow">安全自动化</p>
        <h1 className="mt-3 text-3xl font-semibold tracking-tight">{view === "collect" ? "采集新职位" : "投递执行与记录"}</h1>
        <p className="mt-3 max-w-3xl text-slate-500">{view === "collect" ? "搜索并保存职位，挑选后加入投递计划。此页面不会自动投递。" : "执行已确认的投递计划；登录、验证码和风险页面始终由你处理。"}</p>
      </header>
      {view === "collect" && <><section className="panel">
        <div className="flex flex-wrap items-start justify-between gap-4">
          <div>
            <p className="eyebrow">岗位检索平台</p>
            <h2 className="mt-2 text-xl font-semibold">选择要采集的招聘网站</h2>
            <p className="mt-2 text-sm text-slate-500">选择平台后填写检索条件。不同平台使用各自的页面解析规则，采集结果会统一进入职位库。</p>
          </div>
          <div className="inline-flex rounded-xl border border-slate-200 bg-slate-50 p-1" role="tablist" aria-label="岗位检索平台">
            <button aria-selected={searchPlatform === "boss"} className={`rounded-lg px-4 py-2 text-sm font-medium transition ${searchPlatform === "boss" ? "bg-white text-indigo-700 shadow-sm" : "text-slate-500 hover:text-slate-700"}`} onClick={() => setSearchPlatform("boss")} role="tab" type="button">BOSS 直聘</button>
            <button aria-selected={searchPlatform === "zhaopin"} className={`rounded-lg px-4 py-2 text-sm font-medium transition ${searchPlatform === "zhaopin" ? "bg-white text-indigo-700 shadow-sm" : "text-slate-500 hover:text-slate-700"}`} onClick={() => setSearchPlatform("zhaopin")} role="tab" type="button">智联招聘</button>
          </div>
        </div>
      </section>
      {searchPlatform === "boss" ? <BossPluginWorkflow onTasksCreated={load} /> : <ZhaopinPluginWorkflow onCampaignCreated={load} />}
      </>}
      {view === "delivery" && <><section className="panel">
        <div className="flex flex-wrap items-end justify-between gap-4"><div><p className="eyebrow">投递执行</p><h2 className="mt-2 text-xl font-semibold">启动自动化投递</h2><p className="mt-2 text-sm text-slate-500">支持 BOSS 直聘与智联招聘，可在同一计划中逐个投递。请先登录对应平台，并确认平台账号中的简历；系统不会自动上传本地简历。</p></div></div>
        <div className="mt-6 grid gap-4 md:grid-cols-2">
          <label className="text-sm font-medium text-slate-700">投递计划<select className="mt-2 w-full rounded-xl border border-slate-200 bg-white px-4 py-3 font-normal outline-none focus:border-indigo-500" onChange={(event) => setCampaignId(event.target.value)} value={campaignId}><option value="">请选择投递计划</option>{campaigns.filter((campaign) => applications.some((item) => item.campaign_id === campaign.id)).map((campaign) => { const count = applications.filter((item) => item.campaign_id === campaign.id).length; return <option key={campaign.id} value={campaign.id}>{campaign.scoring_mode === "llm" ? "【LLM 深评】" : ""}{campaign.name} · {count} 个排队岗位</option>; })}</select></label>
          <div className="rounded-xl border border-slate-200 bg-slate-50 px-4 py-3 text-sm text-slate-600"><p className="font-medium text-slate-700">投递平台</p><p className="mt-2">{platformSummary} · 共 {selectedApplications.length} 个待投递岗位</p></div>
          {developerMode && <details className="rounded-xl border border-slate-200 bg-slate-50 p-4 text-sm text-slate-600"><summary className="cursor-pointer font-medium text-slate-700">开发测试场景</summary><label className="mt-3 block">模拟结果<select className="mt-2 w-full rounded-xl border border-slate-200 bg-white px-4 py-3 font-normal outline-none focus:border-indigo-500" onChange={(event) => setScenario(event.target.value)} value={scenario}><option value="SUCCESS">正常投递</option><option value="CAPTCHA_REQUIRED">需要人工处理</option><option value="LOGIN_REQUIRED">需要登录</option><option value="RISK_CONTROL">风控暂停</option><option value="UNKNOWN_STATE">未知页面暂停</option><option value="PLATFORM_LIMIT">平台限制</option><option value="DOM_CHANGED">页面结构变化</option></select></label></details>}
        </div>
        <p className="mt-4 rounded-xl border border-amber-200 bg-amber-50 p-4 text-sm leading-6 text-amber-800">点击下方按钮即确认投递这 {automaticApplications.length} 个三天内采集、已排队的 BOSS / 智联岗位。扩展使用一个标签页逐个操作；遇到登录、验证码、简历选择、风控、平台限制或结果不明确时暂停等待人工处理。</p>
        {manualApplications.length > 0 && <div className="mt-4 rounded-xl border border-slate-200 p-4">
          <h3 className="font-medium">{manualApplications.length} 个岗位需手动投递</h3>
          <p className="mt-2 text-sm text-slate-500">这些平台尚未接入自动投递。打开原页操作后，在投递进度中维护实际状态。</p>
          <ul className="mt-3 space-y-2">{manualApplications.map((item) => <li key={item.id} className="flex flex-wrap justify-between gap-2 text-sm"><span>{item.job.title} · {item.platform === "zhaopin" ? "智联招聘" : item.platform}</span>{item.job.source_url && /^https?:\/\//i.test(item.job.source_url) ? <a href={item.job.source_url} rel="noreferrer" target="_blank" className="text-indigo-700">打开岗位原页 ↗</a> : <Link href={`/jobs/${item.job_id}`} className="text-indigo-700">查看详情</Link>}</li>)}</ul>
        </div>}
        {staleQueuedCount > 0 && <p className="mt-3 rounded-xl border border-amber-200 bg-amber-50 p-4 text-sm leading-6 text-amber-800">有 {staleQueuedCount} 个已排队岗位的采集时间超过 3 天，已从一键投递范围排除。重新采集到相同岗位后会自动恢复。</p>}
        <button className="mt-5 rounded-xl bg-indigo-600 px-5 py-3 text-sm font-medium text-white disabled:cursor-not-allowed disabled:opacity-50" disabled={creating || !campaignId || automaticApplications.length === 0} onClick={() => void handleCreate()} type="button">{creating ? "正在启动投递计划…" : `一键投递 ${automaticApplications.length} 个排队岗位`}</button>
        {applications.length === 0 && <p className="mt-4 text-sm text-slate-500">{staleQueuedCount > 0 ? `暂无采集时间在 3 天内的可投递岗位；${staleQueuedCount} 个岗位需要重新采集后恢复。` : "暂无待投递岗位。请先在投递计划中批准候选职位。"}</p>}
      </section>
      {notice && <div className="rounded-xl border border-emerald-200 bg-emerald-50 p-4 text-emerald-800">{notice}</div>}
      {error && <div className="rounded-xl border border-rose-200 bg-rose-50 p-4 text-rose-800">{error}</div>}
      <section>
        <div className="mb-4 flex items-end justify-between"><div><p className="eyebrow">Task History</p><h2 className="mt-2 text-xl font-semibold">按投递计划管理任务</h2></div><span className="text-sm text-slate-500">{taskGroups.length} 个计划任务</span></div>
        {loading && <div className="panel text-center text-slate-500">加载中…</div>}
        {!loading && taskGroups.length === 0 && <div className="panel text-center text-slate-500">还没有投递计划任务记录。</div>}
        <div className="space-y-4">{taskGroups.map((group) => {
          const relatedCampaign = campaigns.find((campaign) => campaign.id === group.campaign_id);
            const processed = group.submitted_count + group.manual_count + group.failed_count + group.cancelled_count;
          const progress = group.task_count > 0 ? Math.round((processed / group.task_count) * 100) : 0;
          const busy = maintainingCampaignId === group.campaign_id;
          const hasActive = group.active_count > 0 || group.waiting_count > 0;
          return <article className="panel" key={group.campaign_id}>
            <div className="flex flex-wrap items-start justify-between gap-4">
              <div><div className="flex flex-wrap items-center gap-2"><h3 className="text-lg font-semibold">{group.campaign_name}</h3>{relatedCampaign?.scoring_mode === "llm" && <LlmDeepScoreBadge kind="plan" />}</div><p className="mt-2 text-sm text-slate-500">{group.platforms.join("、")} · {group.task_count} 个岗位 · 更新于 {new Date(group.updated_at).toLocaleString("zh-CN")}</p></div>
              <span className="rounded-full bg-indigo-50 px-3 py-1 text-xs font-medium text-indigo-700">{statusLabels[group.status]}</span>
            </div>
            <div className="mt-5 h-2 overflow-hidden rounded-full bg-slate-100"><div className="h-full rounded-full bg-indigo-600 transition-all" style={{ width: `${progress}%` }} /></div>
            <div className="mt-4 grid grid-cols-2 gap-3 text-center sm:grid-cols-6">
              <div><p className="text-xs text-slate-400">总岗位</p><p className="mt-1 font-semibold">{group.task_count}</p></div>
              <div><p className="text-xs text-slate-400">已投递</p><p className="mt-1 font-semibold text-emerald-600">{group.submitted_count}</p></div>
              <div><p className="text-xs text-slate-400">需手动投递</p><p className="mt-1 font-semibold text-amber-600">{group.manual_count}</p></div>
              <div><p className="text-xs text-slate-400">执行中</p><p className="mt-1 font-semibold text-indigo-600">{group.active_count}</p></div>
              <div><p className="text-xs text-slate-400">待处理</p><p className="mt-1 font-semibold text-amber-600">{group.waiting_count}</p></div>
              <div><p className="text-xs text-slate-400">失败/取消</p><p className="mt-1 font-semibold text-rose-600">{group.failed_count + group.cancelled_count}</p></div>
            </div>
            <details className="mt-5 rounded-xl border border-slate-200 bg-slate-50 p-4"><summary className="cursor-pointer text-sm font-medium text-slate-700">查看 {group.task_count} 个岗位执行明细</summary><div className="mt-3 divide-y divide-slate-200">{group.items.map((item) => <div className="flex flex-wrap items-center justify-between gap-3 py-3 text-sm" key={item.task.id}><div><p className="font-medium text-slate-700">{item.job_title}</p><p className={`mt-1 text-xs ${item.application_status === "MANUAL_REQUIRED" ? "font-medium text-amber-700" : "text-slate-500"}`}>Application：{applicationStatusLabels[item.application_status] ?? item.application_status} · Task：{statusLabels[item.task.status]}</p>{item.application_status === "MANUAL_REQUIRED" && <p className="mt-1 text-xs text-amber-700">该职位仅支持立即网申，已跳过自动投递，请打开职位原页手动完成。</p>}</div><Link className="font-medium text-indigo-700" href={`/browser-tasks/${item.task.id}`}>执行详情 →</Link></div>)}</div></details>
            <div className="mt-5 flex flex-wrap justify-end gap-3 border-t border-slate-100 pt-4 text-sm"><Link className="rounded-lg border border-slate-200 px-3 py-2 font-medium text-slate-700" href={`/campaigns/${group.campaign_id}`}>查看/维护投递计划</Link>{hasActive && <button className="rounded-lg border border-amber-200 bg-amber-50 px-3 py-2 font-medium text-amber-700 disabled:opacity-40" disabled={busy} onClick={() => void handleCancelGroup(group)} type="button">取消未完成任务</button>}<button className="rounded-lg border border-rose-200 bg-rose-50 px-3 py-2 font-medium text-rose-700 disabled:opacity-40" disabled={busy || hasActive} onClick={() => void handleDeleteGroup(group)} title={hasActive ? "请先取消未完成任务" : "删除任务记录"} type="button">删除任务记录</button></div>
          </article>;
        })}</div>
      </section></>}
    </div>
  );
}

function getTaskLaunchUrl(task: BrowserTask): string | null {
  const actions = task.payload.actions;
  if (!Array.isArray(actions)) return null;
  const first = actions[0];
  if (!first || typeof first !== "object") return null;
  const url = (first as { url?: unknown }).url;
  return typeof url === "string" ? url : null;
}
