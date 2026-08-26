"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";

import {
  createCampaign,
  deleteCampaign,
  getCampaigns,
  getResumes,
  updateCampaign,
  type Campaign,
  type Resume,
} from "../../lib/api";

const statusLabels: Record<Campaign["status"], string> = {
  DRAFT: "草稿",
  RANKING: "排名中",
  WAITING_APPROVAL: "等待确认",
  RUNNING: "运行中",
  PAUSED: "已暂停",
  COMPLETED: "已完成",
  CANCELLED: "已取消",
  FAILED: "失败",
};

export default function CampaignsPage() {
  const router = useRouter();
  const [campaigns, setCampaigns] = useState<Campaign[]>([]);
  const [resumes, setResumes] = useState<Resume[]>([]);
  const [resumeId, setResumeId] = useState("");
  const [name, setName] = useState("AI Agent 求职计划");
  const [keywords, setKeywords] = useState("Agent, LLM, RAG");
  const [cities, setCities] = useState("");
  const [minScore, setMinScore] = useState(50);
  const [maxJobs, setMaxJobs] = useState(10);
  const [loading, setLoading] = useState(true);
  const [creating, setCreating] = useState(false);
  const [maintaining, setMaintaining] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    Promise.all([getCampaigns(), getResumes()])
      .then(([campaignResponse, resumeResponse]) => {
        setCampaigns(campaignResponse.items);
        setResumes(resumeResponse.items);
        const selected = resumeResponse.items.find((resume) => resume.is_default) ?? resumeResponse.items[0];
        setResumeId(selected?.id ?? "");
      })
      .catch(() => setError("无法加载 Campaign 数据，请确认 API 服务已启动。"))
      .finally(() => setLoading(false));
  }, []);

  async function handleCreate() {
    if (!name.trim() || !resumeId) return;
    setCreating(true);
    setError(null);
    try {
      const campaign = await createCampaign({
        name: name.trim(),
        resume_id: resumeId,
        keywords: keywords.split(/[,，]/).map((value) => value.trim()).filter(Boolean),
        target_cities: cities.split(/[,，]/).map((value) => value.trim()).filter(Boolean),
        min_score: minScore,
        max_jobs: maxJobs,
      });
      router.push(`/campaigns/${campaign.id}`);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Campaign 创建失败。");
    } finally {
      setCreating(false);
    }
  }

  async function reloadCampaigns() {
    const response = await getCampaigns();
    setCampaigns(response.items);
  }

  async function handleEdit(campaign: Campaign) {
    const nextName = window.prompt("计划名称", campaign.name);
    if (nextName === null) return;
    const currentKeywords = Array.isArray(campaign.filters.keywords) ? campaign.filters.keywords.join(", ") : "";
    const nextKeywords = window.prompt("关键词（逗号分隔）", currentKeywords);
    if (nextKeywords === null) return;
    const nextCities = window.prompt("目标城市（逗号分隔）", campaign.target_cities.join(", "));
    if (nextCities === null) return;
    const nextMinScore = window.prompt("最低匹配分数", String(campaign.min_score));
    if (nextMinScore === null) return;
    const nextMaxJobs = window.prompt("最大职位数", String(campaign.max_jobs));
    if (nextMaxJobs === null) return;
    setMaintaining(true);
    setError(null);
    try {
      await updateCampaign(campaign.id, {
        name: nextName.trim(),
        keywords: nextKeywords.split(/[,，]/).map((value) => value.trim()).filter(Boolean),
        target_cities: nextCities.split(/[,，]/).map((value) => value.trim()).filter(Boolean),
        min_score: Number(nextMinScore),
        max_jobs: Number(nextMaxJobs),
      });
      await reloadCampaigns();
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "投递计划保存失败。");
    } finally {
      setMaintaining(false);
    }
  }

  async function handleDelete(campaign: Campaign) {
    if (!window.confirm(`确定删除投递计划“${campaign.name}”及其关联投递记录吗？运行中的计划需先取消。`)) return;
    setMaintaining(true);
    setError(null);
    try {
      await deleteCampaign(campaign.id);
      await reloadCampaigns();
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "投递计划删除失败。");
    } finally {
      setMaintaining(false);
    }
  }

  return (
    <div className="mx-auto max-w-7xl space-y-8">
      <header>
        <p className="eyebrow">投递计划</p>
        <h1 className="mt-3 text-3xl font-semibold tracking-tight">管理投递计划</h1>
        <p className="mt-3 max-w-3xl text-slate-500">把职位搜索、智能排名、人工确认和投递队列组织为可暂停、可恢复的计划。</p>
      </header>

      <section className="panel">
        <div className="flex flex-wrap items-end justify-between gap-4">
          <div>
            <p className="eyebrow">Create</p>
            <h2 className="mt-2 text-xl font-semibold">创建投递计划</h2>
          </div>
          <span className="rounded-full bg-amber-50 px-3 py-1 text-xs font-medium text-amber-700">创建后由你手动 Start</span>
        </div>
        <div className="mt-6 grid gap-4 md:grid-cols-2 xl:grid-cols-3">
          <label className="text-sm font-medium text-slate-700">
            名称
            <input className="mt-2 w-full rounded-xl border border-slate-200 px-4 py-3 font-normal outline-none focus:border-indigo-500 focus:ring-4 focus:ring-indigo-100" onChange={(event) => setName(event.target.value)} value={name} />
          </label>
          <label className="text-sm font-medium text-slate-700">
            使用简历
            <select className="mt-2 w-full rounded-xl border border-slate-200 bg-white px-4 py-3 font-normal outline-none focus:border-indigo-500 focus:ring-4 focus:ring-indigo-100" onChange={(event) => setResumeId(event.target.value)} value={resumeId}>
              {resumes.length === 0 && <option value="">暂无简历</option>}
              {resumes.map((resume) => <option key={resume.id} value={resume.id}>{resume.name}{resume.is_default ? "（默认）" : ""}</option>)}
            </select>
          </label>
          <label className="text-sm font-medium text-slate-700">
            关键词
            <input className="mt-2 w-full rounded-xl border border-slate-200 px-4 py-3 font-normal outline-none focus:border-indigo-500 focus:ring-4 focus:ring-indigo-100" onChange={(event) => setKeywords(event.target.value)} placeholder="Agent, LLM, RAG" value={keywords} />
          </label>
          <label className="text-sm font-medium text-slate-700">
            城市
            <input className="mt-2 w-full rounded-xl border border-slate-200 px-4 py-3 font-normal outline-none focus:border-indigo-500 focus:ring-4 focus:ring-indigo-100" onChange={(event) => setCities(event.target.value)} placeholder="北京, 上海, Remote" value={cities} />
          </label>
          <label className="text-sm font-medium text-slate-700">
            Score Threshold · {minScore}
            <input className="mt-4 w-full accent-indigo-600" max="100" min="0" onChange={(event) => setMinScore(Number(event.target.value))} type="range" value={minScore} />
          </label>
          <label className="text-sm font-medium text-slate-700">
            最大职位数
            <input className="mt-2 w-full rounded-xl border border-slate-200 px-4 py-3 font-normal outline-none focus:border-indigo-500 focus:ring-4 focus:ring-indigo-100" max="100" min="1" onChange={(event) => setMaxJobs(Number(event.target.value))} type="number" value={maxJobs} />
          </label>
        </div>
        <button className="mt-5 rounded-xl bg-indigo-600 px-5 py-3 text-sm font-medium text-white transition hover:bg-indigo-700 disabled:cursor-not-allowed disabled:opacity-50" disabled={creating || !name.trim() || !resumeId} onClick={() => void handleCreate()} type="button">
          {creating ? "创建中…" : "创建投递计划"}
        </button>
      </section>

      {error && <div className="rounded-xl border border-rose-200 bg-rose-50 p-4 text-rose-800">{error}</div>}

      <section>
        <div className="mb-4 flex items-end justify-between gap-4">
          <div><p className="eyebrow">计划列表</p><h2 className="mt-2 text-xl font-semibold">已有计划</h2></div>
          <p className="text-sm text-slate-500">{campaigns.length} 个计划</p>
        </div>
        {loading && <div className="panel text-center text-slate-500">加载中…</div>}
        {!loading && campaigns.length === 0 && <div className="panel text-center text-slate-500">还没有投递计划，可以从上方创建。</div>}
        <div className="grid gap-4 lg:grid-cols-2">
          {campaigns.map((campaign) => (
            <article className="panel transition hover:border-indigo-200 hover:shadow-md" key={campaign.id}>
              <div className="flex items-start justify-between gap-4">
                <div><Link className="font-semibold text-slate-900 hover:text-indigo-700" href={`/campaigns/${campaign.id}`}>{campaign.name}</Link><p className="mt-2 text-sm text-slate-500">最低 {campaign.min_score} 分 · 最多 {campaign.max_jobs} 个职位</p></div>
                <span className="rounded-full bg-indigo-50 px-3 py-1 text-xs font-medium text-indigo-700">{statusLabels[campaign.status]}</span>
              </div>
              <div className="mt-5 grid grid-cols-3 gap-3 border-t border-slate-100 pt-4 text-center">
                <div><p className="text-xs text-slate-400">候选</p><p className="mt-1 font-semibold">{campaign.candidate_count}</p></div>
                <div><p className="text-xs text-slate-400">待确认</p><p className="mt-1 font-semibold">{campaign.waiting_approval_count}</p></div>
                <div><p className="text-xs text-slate-400">已排队</p><p className="mt-1 font-semibold">{campaign.queued_count}</p></div>
              </div>
              <div className="mt-4 flex justify-end gap-3 border-t border-slate-100 pt-4 text-sm"><Link className="font-medium text-indigo-700" href={`/campaigns/${campaign.id}`}>查看详情</Link>{campaign.status === "DRAFT" && <button className="font-medium text-indigo-700" disabled={maintaining} onClick={() => void handleEdit(campaign)} type="button">编辑</button>}<button className="font-medium text-rose-600 disabled:opacity-40" disabled={maintaining} onClick={() => void handleDelete(campaign)} type="button">删除</button></div>
            </article>
          ))}
        </div>
      </section>
    </div>
  );
}
