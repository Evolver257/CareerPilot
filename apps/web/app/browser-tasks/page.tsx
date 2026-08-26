"use client";

import Link from "next/link";
import { useEffect, useState } from "react";

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
} from "../../lib/api";
import { BossPluginWorkflow } from "../../components/boss-plugin-workflow";

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

export default function BrowserTasksPage() {
  const [taskGroups, setTaskGroups] = useState<BrowserTaskCampaignGroup[]>([]);
  const [applications, setApplications] = useState<ApplicationListItem[]>([]);
  const [campaigns, setCampaigns] = useState<Campaign[]>([]);
  const [campaignId, setCampaignId] = useState("");
  const [scenario, setScenario] = useState("SUCCESS");
  const [loading, setLoading] = useState(true);
  const [creating, setCreating] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [maintainingCampaignId, setMaintainingCampaignId] = useState<string | null>(null);

  function load() {
    return Promise.all([getBrowserTaskCampaigns(), getApplications(), getCampaigns()]).then(([taskResponse, applicationResponse, campaignResponse]) => {
      const queued = applicationResponse.items.filter((item) => item.status === "QUEUED");
      setTaskGroups(taskResponse.items);
      setApplications(queued);
      setCampaigns(campaignResponse.items);
      setCampaignId((current) => queued.some((item) => item.campaign_id === current) ? current : queued[0]?.campaign_id ?? "");
    });
  }

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
  }, []);

  async function handleCreate() {
    if (!campaignId) return;
    setCreating(true);
    setError(null);
    setNotice(null);
    try {
      const batch = await createCampaignBrowserTasks({ campaign_id: campaignId, scenario, auto_start: true });
      const bossTasks = batch.items.flatMap((task) => {
        if (task.platform !== "boss") return [];
        const url = getTaskLaunchUrl(task);
        return url ? [{ task_id: task.id, url }] : [];
      });
      if (bossTasks.length > 0) {
        window.postMessage({
          source: "careerpilot-web",
          type: "BOSS_TASK_BATCH_LAUNCH_REQUEST",
          request_id: window.crypto.randomUUID(),
          tasks: bossTasks,
        }, window.location.origin);
      }
      const failed = batch.failed_count > 0 ? `，${batch.failed_count} 个创建失败` : "";
      setNotice(`已创建 ${batch.created_count} 个、复用 ${batch.reused_count} 个 Browser Task；${bossTasks.length} 个 BOSS 岗位已进入单标签页串行队列${failed}。每次“立即沟通”成功后自动切换到下一岗位并更新为已投递。`);
      await load();
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Browser Task 创建失败。");
    } finally {
      setCreating(false);
    }
  }

  const selectedApplications = applications.filter((item) => item.campaign_id === campaignId);
  const platformSummary = [...new Set(selectedApplications.map((item) => item.platform))].join("、") || "暂无";

  return (
    <div className="mx-auto max-w-7xl space-y-8">
      <header>
        <p className="eyebrow">安全自动化</p>
        <h1 className="mt-3 text-3xl font-semibold tracking-tight">自动化任务</h1>
        <p className="mt-3 max-w-3xl text-slate-500">采集用户可见的职位，并在你批准后通过本地浏览器执行投递；登录、验证码和风险页面始终由你处理。</p>
      </header>
      <BossPluginWorkflow onTasksCreated={load} />
      <section className="panel">
        <div className="flex flex-wrap items-end justify-between gap-4"><div><p className="eyebrow">New Task</p><h2 className="mt-2 text-xl font-semibold">启动平台 Adapter 投递</h2></div><a className="text-sm font-medium text-indigo-700" href="https://www.zhipin.com/web/geek/jobs" rel="noreferrer" target="_blank">打开 BOSS 直聘 →</a></div>
        <div className="mt-6 grid gap-4 md:grid-cols-2">
          <label className="text-sm font-medium text-slate-700">投递计划<select className="mt-2 w-full rounded-xl border border-slate-200 bg-white px-4 py-3 font-normal outline-none focus:border-indigo-500" onChange={(event) => setCampaignId(event.target.value)} value={campaignId}><option value="">请选择投递计划</option>{campaigns.filter((campaign) => applications.some((item) => item.campaign_id === campaign.id)).map((campaign) => { const count = applications.filter((item) => item.campaign_id === campaign.id).length; return <option key={campaign.id} value={campaign.id}>{campaign.name} · {count} 个排队岗位</option>; })}</select></label>
          <div className="rounded-xl border border-slate-200 bg-slate-50 px-4 py-3 text-sm text-slate-600"><p className="font-medium text-slate-700">自动选择 Platform Adapter</p><p className="mt-2">{platformSummary} · 共 {selectedApplications.length} 个 QUEUED Application</p></div>
          <label className="text-sm font-medium text-slate-700">Adapter 场景<select className="mt-2 w-full rounded-xl border border-slate-200 bg-white px-4 py-3 font-normal outline-none focus:border-indigo-500" onChange={(event) => setScenario(event.target.value)} value={scenario}><option value="SUCCESS">SUCCESS · 正常投递</option><option value="CAPTCHA_REQUIRED">CAPTCHA_REQUIRED · 需要人工处理</option><option value="LOGIN_REQUIRED">LOGIN_REQUIRED · 需要登录</option><option value="RISK_CONTROL">RISK_CONTROL · 风控暂停</option><option value="UNKNOWN_STATE">UNKNOWN_STATE · 未知 DOM 暂停</option><option value="PLATFORM_LIMIT">PLATFORM_LIMIT · 平台限制</option><option value="DOM_CHANGED">DOM_CHANGED · DOM 变化</option></select></label>
        </div>
        <p className="mt-4 rounded-xl border border-amber-200 bg-amber-50 p-4 text-sm leading-6 text-amber-800">点击后会为该计划中所有排队岗位创建任务。BOSS Adapter 只打开一个标签页，完成“立即沟通”后在同一标签页切换到下一岗位；验证码、登录、风控、平台限制和未知页面会暂停等待人工处理。</p>
        <button className="mt-5 rounded-xl bg-indigo-600 px-5 py-3 text-sm font-medium text-white disabled:cursor-not-allowed disabled:opacity-50" disabled={creating || !campaignId || selectedApplications.length === 0} onClick={() => void handleCreate()} type="button">{creating ? "正在启动投递计划…" : `一键投递 ${selectedApplications.length} 个排队岗位`}</button>
        {applications.length === 0 && <p className="mt-4 text-sm text-slate-500">暂无包含 QUEUED Application 的投递计划。请先在 Agent Trace 审批候选职位。</p>}
      </section>
      {notice && <div className="rounded-xl border border-emerald-200 bg-emerald-50 p-4 text-emerald-800">{notice}</div>}
      {error && <div className="rounded-xl border border-rose-200 bg-rose-50 p-4 text-rose-800">{error}</div>}
      <section>
        <div className="mb-4 flex items-end justify-between"><div><p className="eyebrow">Task History</p><h2 className="mt-2 text-xl font-semibold">按投递计划管理任务</h2></div><span className="text-sm text-slate-500">{taskGroups.length} 个计划任务</span></div>
        {loading && <div className="panel text-center text-slate-500">加载中…</div>}
        {!loading && taskGroups.length === 0 && <div className="panel text-center text-slate-500">还没有投递计划任务记录。</div>}
        <div className="space-y-4">{taskGroups.map((group) => {
          const processed = group.submitted_count + group.failed_count + group.cancelled_count;
          const progress = group.task_count > 0 ? Math.round((processed / group.task_count) * 100) : 0;
          const busy = maintainingCampaignId === group.campaign_id;
          const hasActive = group.active_count > 0 || group.waiting_count > 0;
          return <article className="panel" key={group.campaign_id}>
            <div className="flex flex-wrap items-start justify-between gap-4">
              <div><h3 className="text-lg font-semibold">{group.campaign_name}</h3><p className="mt-2 text-sm text-slate-500">{group.platforms.join("、")} · {group.task_count} 个岗位 · 更新于 {new Date(group.updated_at).toLocaleString("zh-CN")}</p></div>
              <span className="rounded-full bg-indigo-50 px-3 py-1 text-xs font-medium text-indigo-700">{statusLabels[group.status]}</span>
            </div>
            <div className="mt-5 h-2 overflow-hidden rounded-full bg-slate-100"><div className="h-full rounded-full bg-indigo-600 transition-all" style={{ width: `${progress}%` }} /></div>
            <div className="mt-4 grid grid-cols-2 gap-3 text-center sm:grid-cols-5">
              <div><p className="text-xs text-slate-400">总岗位</p><p className="mt-1 font-semibold">{group.task_count}</p></div>
              <div><p className="text-xs text-slate-400">已投递</p><p className="mt-1 font-semibold text-emerald-600">{group.submitted_count}</p></div>
              <div><p className="text-xs text-slate-400">执行中</p><p className="mt-1 font-semibold text-indigo-600">{group.active_count}</p></div>
              <div><p className="text-xs text-slate-400">待处理</p><p className="mt-1 font-semibold text-amber-600">{group.waiting_count}</p></div>
              <div><p className="text-xs text-slate-400">失败/取消</p><p className="mt-1 font-semibold text-rose-600">{group.failed_count + group.cancelled_count}</p></div>
            </div>
            <details className="mt-5 rounded-xl border border-slate-200 bg-slate-50 p-4"><summary className="cursor-pointer text-sm font-medium text-slate-700">查看 {group.task_count} 个岗位执行明细</summary><div className="mt-3 divide-y divide-slate-200">{group.items.map((item) => <div className="flex flex-wrap items-center justify-between gap-3 py-3 text-sm" key={item.task.id}><div><p className="font-medium text-slate-700">{item.job_title}</p><p className="mt-1 text-xs text-slate-500">Application：{item.application_status} · Task：{statusLabels[item.task.status]}</p></div><Link className="font-medium text-indigo-700" href={`/browser-tasks/${item.task.id}`}>执行详情 →</Link></div>)}</div></details>
            <div className="mt-5 flex flex-wrap justify-end gap-3 border-t border-slate-100 pt-4 text-sm"><Link className="rounded-lg border border-slate-200 px-3 py-2 font-medium text-slate-700" href={`/campaigns/${group.campaign_id}`}>查看/维护投递计划</Link>{hasActive && <button className="rounded-lg border border-amber-200 bg-amber-50 px-3 py-2 font-medium text-amber-700 disabled:opacity-40" disabled={busy} onClick={() => void handleCancelGroup(group)} type="button">取消未完成任务</button>}<button className="rounded-lg border border-rose-200 bg-rose-50 px-3 py-2 font-medium text-rose-700 disabled:opacity-40" disabled={busy || hasActive} onClick={() => void handleDeleteGroup(group)} title={hasActive ? "请先取消未完成任务" : "删除任务记录"} type="button">删除任务记录</button></div>
          </article>;
        })}</div>
      </section>
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
