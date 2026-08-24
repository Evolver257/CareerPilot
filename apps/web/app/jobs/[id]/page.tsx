"use client";

import Link from "next/link";
import { useParams } from "next/navigation";
import { useEffect, useState } from "react";

import {
  analyzeJob,
  getJob,
  scoreJob,
  type Job,
  type JobAnalysis,
  type JobScore,
} from "../../../lib/api";

const scoreLabels: Array<[keyof JobScore, string]> = [
  ["semantic_score", "语义相似度"],
  ["skill_score", "技能覆盖"],
  ["education_score", "学历匹配"],
  ["experience_score", "经验匹配"],
  ["location_score", "地点偏好"],
  ["preference_score", "综合偏好"],
  ["llm_score", "LLM Judge"],
];

const recommendationLabels: Record<JobScore["recommendation"], string> = {
  strong_apply: "强烈建议投递",
  apply: "建议投递",
  maybe: "谨慎考虑",
  skip: "建议跳过",
};

function ScoreResult({ score }: { score: JobScore }) {
  return (
    <section className="space-y-6">
      <div className="panel overflow-hidden bg-slate-950 text-white">
        <div className="flex flex-wrap items-center justify-between gap-6">
          <div>
            <p className="text-xs font-semibold uppercase tracking-[0.18em] text-indigo-300">Hybrid Match</p>
            <h2 className="mt-3 text-2xl font-semibold">{recommendationLabels[score.recommendation]}</h2>
            <p className="mt-3 max-w-2xl leading-7 text-slate-300">{score.reasoning_summary}</p>
          </div>
          <div className="grid h-28 w-28 place-items-center rounded-full border-8 border-indigo-400/30 bg-indigo-500/10 text-center">
            <div><span className="text-4xl font-semibold">{Math.round(score.final_score)}</span><span className="block text-xs text-slate-400">FINAL SCORE</span></div>
          </div>
        </div>
        <p className="mt-5 text-xs text-slate-500">{score.score_version} · Rules {score.rules_passed ? "passed" : "blocked"}</p>
      </div>

      <div className="panel">
        <p className="eyebrow">Sub Scores</p>
        <h2 className="mt-2 text-xl font-semibold">混合评分构成</h2>
        <div className="mt-5 grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
          {scoreLabels.map(([key, label]) => (
            <div key={key} className="rounded-xl bg-slate-50 p-4">
              <p className="text-xs text-slate-500">{label}</p>
              <p className="mt-2 text-2xl font-semibold text-slate-800">{Math.round(score[key] as number)}</p>
            </div>
          ))}
        </div>
      </div>

      <div className="grid gap-6 lg:grid-cols-2">
        <div className="panel">
          <p className="eyebrow">Strengths</p>
          <h2 className="mt-2 text-xl font-semibold">优势</h2>
          <ul className="mt-4 space-y-2 text-sm leading-6 text-slate-600">
            {score.strengths.map((item) => <li key={item} className="rounded-xl bg-emerald-50 p-3 text-emerald-800">{item}</li>)}
            {score.strengths.length === 0 && <li className="text-slate-400">暂无明显优势。</li>}
          </ul>
        </div>
        <div className="panel">
          <p className="eyebrow">Gaps & Risks</p>
          <h2 className="mt-2 text-xl font-semibold">差距与风险</h2>
          <ul className="mt-4 space-y-2 text-sm leading-6 text-slate-600">
            {[...score.gaps, ...score.risks].map((item) => <li key={item} className="rounded-xl bg-amber-50 p-3 text-amber-800">{item}</li>)}
            {score.gaps.length + score.risks.length === 0 && <li className="text-slate-400">未发现显著风险。</li>}
          </ul>
        </div>
      </div>

      <div className="panel">
        <p className="eyebrow">Skill Match</p>
        <h2 className="mt-2 text-xl font-semibold">技能覆盖</h2>
        <div className="mt-4 flex flex-wrap gap-2">
          {score.matched_skills.map((skill) => <span key={skill} className="rounded-full bg-emerald-50 px-3 py-1 text-sm font-medium text-emerald-700">✓ {skill}</span>)}
          {score.missing_skills.map((skill) => <span key={skill} className="rounded-full bg-rose-50 px-3 py-1 text-sm font-medium text-rose-700">缺失 {skill}</span>)}
        </div>
      </div>

      <div className="panel">
        <div className="flex flex-wrap items-end justify-between gap-3">
          <div><p className="eyebrow">Resume Evidence</p><h2 className="mt-2 text-xl font-semibold">RAG 检索证据</h2></div>
          <span className="text-sm text-slate-500">{score.resume_evidence.length} chunks</span>
        </div>
        <div className="mt-5 space-y-3">
          {score.resume_evidence.map((evidence) => (
            <article key={evidence.chunk_id} className="rounded-xl border border-slate-200 bg-slate-50 p-4">
              <div className="flex flex-wrap items-center justify-between gap-2"><p className="font-medium text-slate-800">{evidence.chunk_type}</p><span className="text-xs text-slate-500">semantic {Math.round(evidence.semantic_score)} · rerank {Math.round(evidence.rerank_score)}</span></div>
              <p className="mt-3 whitespace-pre-wrap text-sm leading-6 text-slate-600">{evidence.content}</p>
            </article>
          ))}
        </div>
      </div>
    </section>
  );
}

export default function JobDetailPage() {
  const params = useParams<{ id: string }>();
  const [job, setJob] = useState<Job | null>(null);
  const [analysis, setAnalysis] = useState<JobAnalysis | null>(null);
  const [matchScore, setMatchScore] = useState<JobScore | null>(null);
  const [analyzing, setAnalyzing] = useState(false);
  const [scoring, setScoring] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!params.id) return;
    getJob(params.id).then(setJob).catch(() => setError("职位不存在或 API 暂不可用。"));
  }, [params.id]);

  async function handleAnalyze() {
    if (!params.id) return;
    setAnalyzing(true);
    setError(null);
    try {
      setAnalysis(await analyzeJob(params.id));
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "职位分析失败。");
    } finally {
      setAnalyzing(false);
    }
  }

  async function handleScore() {
    if (!params.id) return;
    setScoring(true);
    setError(null);
    try {
      setMatchScore(await scoreJob(params.id));
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "职位匹配评分失败。");
    } finally {
      setScoring(false);
    }
  }

  return (
    <div className="mx-auto max-w-4xl space-y-6">
      <Link className="text-sm font-medium text-indigo-700 hover:text-indigo-900" href="/jobs">← 返回职位列表</Link>
      {error && <div className="rounded-xl border border-rose-200 bg-rose-50 p-4 text-rose-800">{error}</div>}
      {!job && !error && <div className="panel text-slate-500">加载中…</div>}
      {job && (
        <>
          <header className="panel">
            <div className="flex flex-wrap items-start justify-between gap-4">
              <div>
                <p className="eyebrow">{job.platform}</p>
                <h1 className="mt-3 text-3xl font-semibold">{job.title}</h1>
                <p className="mt-3 text-slate-500">{job.location ?? "地点未填写"} · {job.job_type ?? "类型未填写"}</p>
              </div>
              <div className="flex flex-wrap gap-2">
                <button className="rounded-xl border border-slate-200 px-4 py-2.5 text-sm font-medium text-slate-700 transition hover:border-indigo-300 hover:text-indigo-700 disabled:cursor-not-allowed disabled:opacity-50" disabled={analyzing} onClick={() => void handleAnalyze()} type="button">
                  {analyzing ? "解析中…" : analysis ? "重新解析" : "解析职位"}
                </button>
                <button className="rounded-xl bg-indigo-600 px-4 py-2.5 text-sm font-medium text-white transition hover:bg-indigo-700 disabled:cursor-not-allowed disabled:opacity-50" disabled={scoring} onClick={() => void handleScore()} type="button">
                  {scoring ? "评分中…" : matchScore ? "重新评分" : "计算匹配"}
                </button>
              </div>
            </div>
          </header>
          <section className="panel">
            <p className="eyebrow">Job Description</p>
            <h2 className="mt-2 text-xl font-semibold">职位描述</h2>
            <p className="mt-4 whitespace-pre-wrap leading-7 text-slate-600">{job.description}</p>
          </section>
          {matchScore && <ScoreResult score={matchScore} />}
          {analysis ? <section className="space-y-6">
            <div className="panel">
              <p className="eyebrow">Structured Job</p>
              <h2 className="mt-2 text-xl font-semibold">结构化职位</h2>
              <p className="mt-3 leading-7 text-slate-600">{analysis.structured_job.summary || "已完成结构化解析。"}</p>
              <div className="mt-5 grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
                {[["Role Category", analysis.structured_job.role_category], ["Level", analysis.structured_job.level], ["Job Type", analysis.structured_job.job_type], ["Location", analysis.structured_job.location || "—"]].map(([label, value]) => <div key={label} className="rounded-xl bg-slate-50 p-4"><p className="text-xs text-slate-500">{label}</p><p className="mt-2 font-medium text-slate-800">{value}</p></div>)}
              </div>
            </div>
            <div className="grid gap-6 lg:grid-cols-2">
              <div className="panel">
                <p className="eyebrow">Skills</p>
                <h2 className="mt-2 text-xl font-semibold">技能要求</h2>
                <div className="mt-4 flex flex-wrap gap-2">{analysis.skills.map((skill) => <span key={skill.id} className={`rounded-full px-3 py-1 text-sm font-medium ${skill.skill_type === "preferred" ? "bg-amber-50 text-amber-700" : "bg-indigo-50 text-indigo-700"}`}>{skill.skill_name} · {skill.skill_type}</span>)}</div>
              </div>
              <div className="panel">
                <p className="eyebrow">Requirements</p>
                <h2 className="mt-2 text-xl font-semibold">经验与学历</h2>
                <p className="mt-4 text-sm leading-6 text-slate-600">{analysis.requirements.education || "未识别学历要求"}</p>
                <p className="mt-2 text-sm leading-6 text-slate-600">{analysis.requirements.experience || "未识别经验要求"}</p>
              </div>
            </div>
            <div className="panel">
              <p className="eyebrow">Responsibilities</p>
              <h2 className="mt-2 text-xl font-semibold">岗位职责</h2>
              <ul className="mt-4 space-y-2 text-sm leading-6 text-slate-600">{analysis.requirements.responsibilities.map((item) => <li key={item} className="rounded-xl bg-slate-50 p-3">{item}</li>)}</ul>
            </div>
          </section> : <section className="grid gap-4 sm:grid-cols-2">
            <div className="panel"><p className="eyebrow">Job Intelligence</p><p className="mt-3 text-slate-500">点击“解析职位”提取结构化字段、技能和要求。</p></div>
            <div className="panel"><p className="eyebrow">Matching</p><p className="mt-3 text-slate-500">Phase 4 开放智能匹配。</p></div>
          </section>}
        </>
      )}
    </div>
  );
}
