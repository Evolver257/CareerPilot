"use client";

import Link from "next/link";
import { useEffect, useState } from "react";

import {
  createCampaignBrowserTasks,
  getApplications,
  getBrowserTasks,
  getCampaigns,
  type ApplicationListItem,
  type BrowserTask,
  type Campaign,
} from "../../lib/api";
import { BossPluginWorkflow } from "../../components/boss-plugin-workflow";

const statusLabels: Record<BrowserTask["status"], string> = {
  PENDING: "待启动",
  CONNECTING: "等待 Extension",
  RUNNING: "执行中",
  WAITING_FOR_USER: "等待人工处理",
  COMPLETED: "已完成",
  CANCELLED: "已取消",
  FAILED: "失败",
};

export default function BrowserTasksPage() {
  const [tasks, setTasks] = useState<BrowserTask[]>([]);
  const [applications, setApplications] = useState<ApplicationListItem[]>([]);
  const [campaigns, setCampaigns] = useState<Campaign[]>([]);
  const [campaignId, setCampaignId] = useState("");
  const [scenario, setScenario] = useState("SUCCESS");
  const [loading, setLoading] = useState(true);
  const [creating, setCreating] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);

  function load() {
    return Promise.all([getBrowserTasks(), getApplications(), getCampaigns()]).then(([taskResponse, applicationResponse, campaignResponse]) => {
      const queued = applicationResponse.items.filter((item) => item.status === "QUEUED");
      setTasks(taskResponse.items);
      setApplications(queued);
      setCampaigns(campaignResponse.items);
      setCampaignId((current) => queued.some((item) => item.campaign_id === current) ? current : queued[0]?.campaign_id ?? "");
    });
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
        <div className="mb-4 flex items-end justify-between"><div><p className="eyebrow">Task History</p><h2 className="mt-2 text-xl font-semibold">任务记录</h2></div><span className="text-sm text-slate-500">{tasks.length} tasks</span></div>
        {loading && <div className="panel text-center text-slate-500">加载中…</div>}
        {!loading && tasks.length === 0 && <div className="panel text-center text-slate-500">还没有 Browser Task。</div>}
        <div className="grid gap-4 lg:grid-cols-2">{tasks.map((task) => <Link className="panel block transition hover:-translate-y-0.5 hover:border-indigo-200 hover:shadow-md" href={`/browser-tasks/${task.id}`} key={task.id}><div className="flex items-start justify-between gap-4"><div><h3 className="font-semibold">{task.platform} Application · {task.application_id.slice(0, 8)}</h3><p className="mt-2 text-xs text-slate-500">{task.scenario} · {task.action_sequence} actions</p></div><span className="rounded-full bg-indigo-50 px-3 py-1 text-xs font-medium text-indigo-700">{statusLabels[task.status]}</span></div><div className="mt-5 flex justify-between border-t border-slate-100 pt-4 text-sm text-slate-500"><span>{task.events.length} events</span><span>{new Date(task.created_at).toLocaleString("zh-CN")}</span></div></Link>)}</div>
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
