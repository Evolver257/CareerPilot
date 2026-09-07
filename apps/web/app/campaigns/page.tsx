"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useRef, useState } from "react";
import { parseCampaignNumbers } from "../../lib/campaign-input";

import { LlmDeepScoreBadge } from "../../components/scoring-mode-badge";
import {
  createCampaign,
  deleteCampaign,
  getCampaigns,
  getResumes,
  updateCampaign,
  type Campaign,
  type RankingScoringMode,
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
  const [maxJobs, setMaxJobs] = useState("10");
  const [scoringMode, setScoringMode] = useState<RankingScoringMode>("fast");
  const [loading, setLoading] = useState(true);
  const [creating, setCreating] = useState(false);
  const [maintaining, setMaintaining] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [editingCampaign, setEditingCampaign] = useState<Campaign | null>(null);
  const [editName, setEditName] = useState("");
  const [editKeywords, setEditKeywords] = useState("");
  const [editCities, setEditCities] = useState("");
  const [editMinScore, setEditMinScore] = useState("50");
  const [editMaxJobs, setEditMaxJobs] = useState("10");
  const [editError, setEditError] = useState<string | null>(null);
  const editPanel = useRef<HTMLElement>(null);
  const editInput = useRef<HTMLInputElement>(null);

  useEffect(() => {
    if (!editingCampaign) return;
    editPanel.current?.scrollIntoView({ block: "start" });
    editInput.current?.focus({ preventScroll: true });
  }, [editingCampaign]);

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
        ...parseCampaignNumbers(maxJobs, String(minScore)),
        scoring_mode: scoringMode,
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

  function beginEdit(campaign: Campaign) {
    setEditError(null);
    setEditingCampaign(campaign);
    setEditName(campaign.name);
    setEditKeywords(Array.isArray(campaign.filters.keywords) ? campaign.filters.keywords.join(", ") : "");
    setEditCities(campaign.target_cities.join(", "));
    setEditMinScore(String(campaign.min_score));
    setEditMaxJobs(String(campaign.max_jobs));
  }

  async function handleEdit() {
    if (!editingCampaign || !editName.trim()) return;
    setMaintaining(true);
    setEditError(null);
    try {
      await updateCampaign(editingCampaign.id, {
        name: editName.trim(),
        keywords: editKeywords.split(/[,，]/).map((value) => value.trim()).filter(Boolean),
        target_cities: editCities.split(/[,，]/).map((value) => value.trim()).filter(Boolean),
        ...parseCampaignNumbers(editMaxJobs, editMinScore),
      });
      await reloadCampaigns();
      setEditingCampaign(null);
    } catch (reason) {
      setEditError(reason instanceof Error ? reason.message : "投递计划保存失败。");
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

      {editingCampaign && <section ref={editPanel} aria-labelledby="edit-campaign-title" className="panel scroll-mt-6 border-indigo-200">
        <div className="flex flex-wrap items-start justify-between gap-4">
          <div><p className="eyebrow">维护计划</p><h2 className="mt-2 text-xl font-semibold" id="edit-campaign-title">编辑投递计划</h2><p className="mt-2 text-sm text-slate-500">一次核对全部条件，保存后不会改变已经完成的投递记录。</p></div>
          <button className="text-sm text-slate-500" disabled={maintaining} onClick={() => setEditingCampaign(null)} type="button">关闭</button>
        </div>
        <div className="mt-6 grid gap-4 md:grid-cols-2 xl:grid-cols-3">
          <label className="text-sm font-medium text-slate-700">计划名称<input ref={editInput} className="mt-2 w-full rounded-xl border border-slate-200 px-4 py-3 font-normal outline-none focus:border-indigo-500 focus:ring-4 focus:ring-indigo-100" onChange={(event) => setEditName(event.target.value)} value={editName} /></label>
          <label className="text-sm font-medium text-slate-700">关键词<input className="mt-2 w-full rounded-xl border border-slate-200 px-4 py-3 font-normal outline-none focus:border-indigo-500 focus:ring-4 focus:ring-indigo-100" onChange={(event) => setEditKeywords(event.target.value)} placeholder="Agent，RAG，Python" value={editKeywords} /></label>
          <label className="text-sm font-medium text-slate-700">目标城市<input className="mt-2 w-full rounded-xl border border-slate-200 px-4 py-3 font-normal outline-none focus:border-indigo-500 focus:ring-4 focus:ring-indigo-100" onChange={(event) => setEditCities(event.target.value)} placeholder="北京，上海" value={editCities} /></label>
          <label className="text-sm font-medium text-slate-700">最低匹配分数<input className="mt-2 w-full rounded-xl border border-slate-200 px-4 py-3 font-normal outline-none focus:border-indigo-500 focus:ring-4 focus:ring-indigo-100" max={100} min={0} step="any" onChange={(event) => setEditMinScore(event.target.value)} type="number" value={editMinScore} /></label>
          <label className="text-sm font-medium text-slate-700">最多职位数<input className="mt-2 w-full rounded-xl border border-slate-200 px-4 py-3 font-normal outline-none focus:border-indigo-500 focus:ring-4 focus:ring-indigo-100" max={200} min={1} step={1} onChange={(event) => setEditMaxJobs(event.target.value)} type="number" value={editMaxJobs} /></label>
        </div>
        {editError && <p role="alert" className="mt-4 rounded-xl bg-rose-50 p-3 text-sm text-rose-800">{editError}</p>}
        <div className="mt-5 flex gap-3"><button className="rounded-xl bg-indigo-600 px-5 py-2.5 text-sm font-medium text-white transition hover:bg-indigo-700 disabled:opacity-50" disabled={maintaining || !editName.trim()} onClick={() => void handleEdit()} type="button">{maintaining ? "保存中…" : "保存修改"}</button><button className="rounded-xl border border-slate-200 px-5 py-2.5 text-sm font-medium text-slate-700" disabled={maintaining} onClick={() => setEditingCampaign(null)} type="button">取消</button></div>
      </section>}

      <section className="panel">
        <div className="flex flex-wrap items-end justify-between gap-4">
          <div>
            <p className="eyebrow">新建计划</p>
            <h2 className="mt-2 text-xl font-semibold">创建投递计划</h2>
          </div>
          <span className="rounded-full bg-amber-50 px-3 py-1 text-xs font-medium text-amber-700">创建后由你确认并启动</span>
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
            <input className="mt-2 w-full rounded-xl border border-slate-200 px-4 py-3 font-normal outline-none focus:border-indigo-500 focus:ring-4 focus:ring-indigo-100" max="200" min="1" step={1} onChange={(event) => setMaxJobs(event.target.value)} type="number" value={maxJobs} />
          </label>
          <fieldset className="md:col-span-2 xl:col-span-3">
            <legend className="text-sm font-medium text-slate-700">匹配评分方式</legend>
            <div className="mt-2 grid gap-3 md:grid-cols-2">
              <label className={`cursor-pointer rounded-xl border p-4 transition ${scoringMode === "fast" ? "border-indigo-500 bg-indigo-50 ring-2 ring-indigo-100" : "border-slate-200"}`}>
                <input checked={scoringMode === "fast"} className="mr-3 accent-indigo-600" name="scoring-mode" onChange={() => setScoringMode("fast")} type="radio" />
                <span className="font-semibold text-slate-900">快速评分</span>
                <span className="mt-1 block pl-7 text-xs leading-5 text-slate-500">不调用 LLM，使用语义、技能、学历、经验和偏好综合评分，适合批量计划。</span>
              </label>
              <label className={`cursor-pointer rounded-xl border p-4 transition ${scoringMode === "llm" ? "border-violet-500 bg-violet-50 ring-2 ring-violet-100" : "border-slate-200"}`}>
                <input checked={scoringMode === "llm"} className="mr-3 accent-violet-600" name="scoring-mode" onChange={() => setScoringMode("llm")} type="radio" />
                <span className="font-semibold text-slate-900">LLM 深度评分</span>
                <span className="mt-1 block pl-7 text-xs leading-5 text-slate-500">逐个深度判断，质量更高但耗时和 API 成本随最大职位数增加；任务将在后台运行。</span>
              </label>
            </div>
          </fieldset>
        </div>
        <button className="mt-5 rounded-xl bg-indigo-600 px-5 py-3 text-sm font-medium text-white transition hover:bg-indigo-700 disabled:cursor-not-allowed disabled:opacity-50" disabled={creating || !name.trim() || !resumeId} onClick={() => void handleCreate()} type="button">
          {creating ? "创建中…" : "创建投递计划"}
        </button>
      </section>

      {error && <div role="alert" className="rounded-xl border border-rose-200 bg-rose-50 p-4 text-rose-800">{error}</div>}

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
                <div><div className="flex flex-wrap items-center gap-2"><Link className="font-semibold text-slate-900 hover:text-indigo-700" href={`/campaigns/${campaign.id}`}>{campaign.name}</Link>{campaign.scoring_mode === "llm" && <LlmDeepScoreBadge kind="plan" />}</div><p className="mt-2 text-sm text-slate-500">最低 {campaign.min_score} 分 · 最多 {campaign.max_jobs} 个职位 · {campaign.scoring_mode === "llm" ? "模型深度复核" : "快速评分"}</p></div>
                <span className="rounded-full bg-indigo-50 px-3 py-1 text-xs font-medium text-indigo-700">{statusLabels[campaign.status]}</span>
              </div>
              <div className="mt-5 grid grid-cols-3 gap-3 border-t border-slate-100 pt-4 text-center">
                <div><p className="text-xs text-slate-400">候选</p><p className="mt-1 font-semibold">{campaign.candidate_count}</p></div>
                <div><p className="text-xs text-slate-400">待确认</p><p className="mt-1 font-semibold">{campaign.waiting_approval_count}</p></div>
                <div><p className="text-xs text-slate-400">已排队</p><p className="mt-1 font-semibold">{campaign.queued_count}</p></div>
              </div>
              <div className="mt-4 flex justify-end gap-3 border-t border-slate-100 pt-4 text-sm"><Link className="font-medium text-indigo-700" href={`/campaigns/${campaign.id}`}>查看详情</Link>{campaign.status === "DRAFT" && <button className="font-medium text-indigo-700" disabled={maintaining} onClick={() => beginEdit(campaign)} type="button">编辑</button>}<button className="font-medium text-rose-600 disabled:opacity-40" disabled={maintaining} onClick={() => void handleDelete(campaign)} type="button">删除</button></div>
            </article>
          ))}
        </div>
      </section>
    </div>
  );
}
