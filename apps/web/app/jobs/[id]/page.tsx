"use client";

import Link from "next/link";
import { useParams } from "next/navigation";
import { useEffect, useState } from "react";

import {
  analyzeJob,
  getJob,
  getJobs,
  type Job,
  type JobAnalysis,
} from "../../../lib/api";

type JobNeighbors = {
  previous: Job | null;
  next: Job | null;
};

function getRawText(job: Job, key: string): string | null {
  const value = job.raw_data[key];
  return typeof value === "string" && value.trim() ? value.trim() : null;
}

function getCompanyName(job: Job): string {
  return getRawText(job, "company_name")
    ?? (job.company_id ? "已关联公司" : "未注明公司");
}

function getSalaryText(job: Job, analysis?: JobAnalysis | null): string {
  const capturedSalary = getRawText(job, "salary_text");
  if (capturedSalary && !/[\uE000-\uF8FF]/.test(capturedSalary)) return capturedSalary;

  const minimum = job.salary_min ?? analysis?.structured_job.salary.minimum ?? null;
  const maximum = job.salary_max ?? analysis?.structured_job.salary.maximum ?? null;
  if (minimum !== null && maximum !== null) return `${minimum} - ${maximum}`;
  if (minimum !== null) return `${minimum}+`;
  if (maximum !== null) return `最高 ${maximum}`;
  return "薪资面议";
}

function JobSwitcher({ neighbors }: { neighbors: JobNeighbors }) {
  return (
    <div className="flex flex-wrap items-center justify-between gap-3 rounded-2xl border border-slate-200 bg-white px-4 py-3 shadow-sm">
      <span className="text-sm text-slate-500">职位浏览</span>
      <div className="flex gap-2">
        {neighbors.previous ? (
          <Link className="rounded-lg border border-slate-200 px-3 py-2 text-sm font-medium text-slate-700 transition hover:border-indigo-300 hover:text-indigo-700" href={`/jobs/${neighbors.previous.id}`}>
            ← 上一职位
          </Link>
        ) : (
          <button className="rounded-lg border border-slate-200 px-3 py-2 text-sm font-medium text-slate-400" disabled type="button">← 上一职位</button>
        )}
        {neighbors.next ? (
          <Link className="rounded-lg border border-slate-200 px-3 py-2 text-sm font-medium text-slate-700 transition hover:border-indigo-300 hover:text-indigo-700" href={`/jobs/${neighbors.next.id}`}>
            下一职位 →
          </Link>
        ) : (
          <button className="rounded-lg border border-slate-200 px-3 py-2 text-sm font-medium text-slate-400" disabled type="button">下一职位 →</button>
        )}
      </div>
    </div>
  );
}

function RequirementList({ items, empty }: { items: string[]; empty: string }) {
  return (
    <ul className="mt-4 space-y-2 text-sm leading-6 text-slate-600">
      {items.map((item) => <li className="flex gap-3 rounded-xl bg-slate-50 p-3" key={item}><span className="mt-0.5 text-indigo-500">•</span><span>{item}</span></li>)}
      {items.length === 0 && empty && <li className="text-slate-400">{empty}</li>}
    </ul>
  );
}

function StructuredJobDescription({ analysis, rawDescription }: { analysis: JobAnalysis; rawDescription: string }) {
  const profile = analysis.structured_job;
  const requiredSkills = analysis.skills.filter((skill) => skill.skill_type !== "preferred");
  const preferredSkills = analysis.skills.filter((skill) => skill.skill_type === "preferred");
  return (
    <section className="space-y-6">
      <div className="panel">
        <div className="flex flex-wrap items-start justify-between gap-4">
          <div><p className="eyebrow">结构化 JD</p><h2 className="mt-2 text-xl font-semibold">职位概览</h2></div>
          <span className="rounded-full bg-emerald-50 px-3 py-1 text-xs font-medium text-emerald-700">已自动解析</span>
        </div>
        <div className="mt-5 grid gap-3 md:grid-cols-2">
          <div className="rounded-2xl border border-indigo-200 bg-indigo-50 p-4">
            <p className="text-xs font-semibold text-indigo-600">学历要求</p>
            <p className="mt-2 text-lg font-semibold text-indigo-950">{analysis.requirements.education || profile.education_requirement || "未注明学历要求"}</p>
          </div>
          <div className="rounded-2xl border border-slate-200 bg-slate-50 p-4">
            <p className="text-xs font-semibold text-slate-500">经验要求</p>
            <p className="mt-2 text-lg font-semibold text-slate-800">{analysis.requirements.experience || profile.experience_requirement || "未注明经验要求"}</p>
          </div>
        </div>
        <p className="mt-4 leading-7 text-slate-600">{profile.summary || "职位信息已完成结构化解析。"}</p>
        <div className="mt-5 grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
          {[["职位方向", profile.role_category], ["职级", profile.level], ["工作性质", profile.job_type], ["地点", profile.location || "未注明"]].map(([label, value]) => <div key={label} className="rounded-xl bg-slate-50 p-4"><p className="text-xs text-slate-500">{label}</p><p className="mt-2 font-medium text-slate-800">{value}</p></div>)}
        </div>
      </div>

      <div className="grid gap-6 lg:grid-cols-2">
        <div className="panel"><div className="flex items-center justify-between gap-3"><div><p className="eyebrow">工作内容</p><h2 className="mt-2 text-xl font-semibold">岗位职责</h2></div><span className="rounded-full bg-indigo-50 px-3 py-1 text-xs font-medium text-indigo-700">已识别 {analysis.requirements.responsibilities.length} 条</span></div><RequirementList empty="未单独识别岗位职责，请查看原始 JD。" items={analysis.requirements.responsibilities} /></div>
        <div className="panel"><p className="eyebrow">候选人要求</p><h2 className="mt-2 text-xl font-semibold">任职条件</h2><RequirementList empty="未单独识别任职条件，请查看原始 JD。" items={analysis.requirements.qualifications} />{(analysis.requirements.education || analysis.requirements.experience) && <div className="mt-4 space-y-2 border-t border-slate-100 pt-4 text-sm text-slate-600">{analysis.requirements.education && <p><span className="font-medium text-slate-800">学历：</span>{analysis.requirements.education}</p>}{analysis.requirements.experience && <p><span className="font-medium text-slate-800">经验：</span>{analysis.requirements.experience}</p>}</div>}</div>
      </div>

      <div className="panel">
        <div className="grid gap-6 lg:grid-cols-2">
          <div><p className="eyebrow">核心能力</p><h2 className="mt-2 text-xl font-semibold">技能要求</h2><div className="mt-4 flex flex-wrap gap-2">{requiredSkills.map((skill) => <span className="rounded-full bg-indigo-50 px-3 py-1 text-sm font-medium text-indigo-700" key={skill.id}>{skill.skill_name}</span>)}{requiredSkills.length === 0 && <span className="text-sm text-slate-400">未识别明确技能</span>}</div></div>
          <div><p className="eyebrow">优先考虑</p><h2 className="mt-2 text-xl font-semibold">加分项</h2><div className="mt-4 flex flex-wrap gap-2">{preferredSkills.map((skill) => <span className="rounded-full bg-amber-50 px-3 py-1 text-sm font-medium text-amber-700" key={skill.id}>{skill.skill_name}</span>)}</div><RequirementList empty={preferredSkills.length ? "" : "未识别加分项"} items={analysis.requirements.preferred_qualifications} /></div>
        </div>
      </div>

      <details className="panel group">
        <summary className="cursor-pointer font-semibold text-slate-800">查看原始职位描述</summary>
        <div className="mt-4 whitespace-pre-wrap rounded-xl bg-slate-50 p-5 text-sm leading-7 text-slate-600">{rawDescription}</div>
      </details>
    </section>
  );
}

export default function JobDetailPage() {
  const params = useParams<{ id: string }>();
  const [job, setJob] = useState<Job | null>(null);
  const [analysis, setAnalysis] = useState<JobAnalysis | null>(null);
  const [analyzing, setAnalyzing] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [analysisError, setAnalysisError] = useState<string | null>(null);
  const [neighbors, setNeighbors] = useState<JobNeighbors>({ previous: null, next: null });

  useEffect(() => {
    if (!params.id) return;
    let cancelled = false;
    async function loadDetail() {
      setAnalyzing(true);
      setError(null);
      setAnalysisError(null);
      try {
        const [loadedJob, loadedAnalysis] = await Promise.all([
          getJob(params.id),
          analyzeJob(params.id),
        ]);
        if (cancelled) return;
        setJob(loadedAnalysis.job ?? loadedJob);
        setAnalysis(loadedAnalysis);
        setAnalyzing(false);
      } catch (reason) {
        if (cancelled) return;
        try {
          setJob(await getJob(params.id));
          setAnalysisError(reason instanceof Error ? reason.message : "职位自动解析失败。");
        } catch {
          setError("职位不存在或 API 暂不可用。");
        }
      } finally {
        if (!cancelled) {
          setAnalyzing(false);
        }
      }
    }
    void loadDetail();
    return () => { cancelled = true; };
  }, [params.id]);

  useEffect(() => {
    if (!params.id) return;
    let cancelled = false;
    getJobs({ page: 1, page_size: 100 })
      .then((response) => {
        if (cancelled) return;
        const index = response.items.findIndex((item) => item.id === params.id);
        setNeighbors({
          previous: index > 0 ? response.items[index - 1] : null,
          next: index >= 0 && index < response.items.length - 1 ? response.items[index + 1] : null,
        });
      })
      .catch(() => {
        if (!cancelled) setNeighbors({ previous: null, next: null });
      });
    return () => { cancelled = true; };
  }, [params.id]);

  async function handleAnalyze() {
    if (!params.id) return;
    setAnalyzing(true);
    setAnalysisError(null);
    try {
      const nextAnalysis = await analyzeJob(params.id);
      setAnalysis(nextAnalysis);
      setJob(nextAnalysis.job);
    } catch (reason) {
      setAnalysisError(reason instanceof Error ? reason.message : "职位分析失败。");
    } finally {
      setAnalyzing(false);
    }
  }

  return (
    <div className="mx-auto max-w-4xl space-y-6">
      <Link className="text-sm font-medium text-indigo-700 hover:text-indigo-900" href="/jobs">← 返回职位列表</Link>
      <JobSwitcher neighbors={neighbors} />
      {error && <div className="rounded-xl border border-rose-200 bg-rose-50 p-4 text-rose-800">{error}</div>}
      {analysisError && <div className="rounded-xl border border-amber-200 bg-amber-50 p-4 text-amber-800">职位已加载，但自动解析暂时失败：{analysisError}</div>}
      {!job && !error && <div className="panel text-slate-500">加载中…</div>}
      {job && (
        <>
          <header className="panel">
            <div className="flex flex-wrap items-start justify-between gap-4">
              <div>
                <p className="eyebrow">{job.platform}</p>
                <h1 className="mt-3 text-3xl font-semibold">{job.title}</h1>
                <div className="mt-5 grid gap-3 sm:grid-cols-2">
                  <div className="rounded-2xl border border-emerald-200 bg-emerald-50 p-4">
                    <p className="text-xs font-semibold text-emerald-700">薪资</p>
                    <p className="mt-2 text-xl font-semibold text-emerald-900">{getSalaryText(job, analysis)}</p>
                  </div>
                  <div className="rounded-2xl border border-indigo-200 bg-indigo-50 p-4">
                    <p className="text-xs font-semibold text-indigo-700">公司</p>
                    <p className="mt-2 text-xl font-semibold text-indigo-950">{getCompanyName(job)}</p>
                  </div>
                </div>
                <div className="mt-4 flex flex-wrap gap-2 text-sm">
                  <span className="rounded-full bg-slate-100 px-3 py-1.5 text-slate-700">地点 · {job.location ?? "未注明"}</span>
                  <span className="rounded-full bg-slate-100 px-3 py-1.5 text-slate-700">类型 · {job.job_type ?? "未注明"}</span>
                  <span className="rounded-full bg-indigo-50 px-3 py-1.5 font-medium text-indigo-700">学历 · {job.education_requirement || analysis?.requirements.education || "未注明"}</span>
                  <span className="rounded-full bg-slate-100 px-3 py-1.5 text-slate-700">经验 · {job.experience_requirement || analysis?.requirements.experience || "未注明"}</span>
                </div>
              </div>
              <div className="flex flex-wrap gap-2">
                <span className={`rounded-xl px-4 py-2.5 text-sm font-medium ${analyzing ? "bg-amber-50 text-amber-700" : "bg-emerald-50 text-emerald-700"}`}>{analyzing ? "正在解析 JD…" : "职位分析已就绪"}</span>
                {job.source_url && <a className="rounded-xl border border-slate-200 px-4 py-2.5 text-sm font-medium text-slate-700 transition hover:border-indigo-300 hover:text-indigo-700" href={job.source_url} rel="noreferrer" target="_blank">BOSS 原页面</a>}
                <button className="rounded-xl border border-slate-200 px-4 py-2.5 text-sm font-medium text-slate-700 transition hover:border-indigo-300 hover:text-indigo-700 disabled:cursor-not-allowed disabled:opacity-50" disabled={analyzing} onClick={() => void handleAnalyze()} type="button">
                  {analyzing ? "解析中…" : "刷新解析"}
                </button>
              </div>
            </div>
          </header>
          {analysis ? <StructuredJobDescription analysis={analysis} rawDescription={job.description} /> : analyzing && <section className="panel animate-pulse text-slate-500">正在提取岗位职责、任职条件和技能要求…</section>}
        </>
      )}
    </div>
  );
}
