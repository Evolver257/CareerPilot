"use client";

import Link from "next/link";
import { useEffect, useState } from "react";

import {
  getResumes,
  rankJobs,
  type JobRankingResponse,
  type RankingStageName,
  type Resume,
} from "../../lib/api";

const stageLabels: Record<RankingStageName, string> = {
  rule_filter: "Rule Filter",
  embedding_rank: "Embedding Rank",
  reranker: "Reranker",
  llm_judge: "LLM Judge",
  final_ranking: "Final Ranking",
};

const recommendationLabels = {
  strong_apply: "强烈建议",
  apply: "建议投递",
  maybe: "可以考虑",
  skip: "暂时跳过",
};

export default function RankingPage() {
  const [resumes, setResumes] = useState<Resume[]>([]);
  const [resumeId, setResumeId] = useState("");
  const [result, setResult] = useState<JobRankingResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    getResumes()
      .then((response) => {
        setResumes(response.items);
        const selected = response.items.find((resume) => resume.is_default) ?? response.items[0];
        setResumeId(selected?.id ?? "");
      })
      .catch(() => setError("无法加载简历，请确认 API 服务已启动。"));
  }, []);

  async function handleRank() {
    setLoading(true);
    setError(null);
    try {
      setResult(await rankJobs(resumeId || undefined));
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "职位排名失败。");
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="mx-auto max-w-7xl space-y-8">
      <header className="flex flex-wrap items-end justify-between gap-5">
        <div>
          <p className="eyebrow">Cost-aware Ranking Pipeline</p>
          <h1 className="mt-3 text-3xl font-semibold tracking-tight">智能职位排名</h1>
          <p className="mt-3 max-w-3xl text-slate-500">
            规则、向量召回、重排与 LLM 深度判断逐层收敛，只让高潜力职位进入高成本阶段。
          </p>
        </div>
        {result && (
          <div className="rounded-2xl border border-indigo-100 bg-indigo-50 px-5 py-3 text-sm text-indigo-800">
            <span className="font-semibold">{result.trace.version}</span>
            <span className="mx-2 text-indigo-300">·</span>
            LLM 调用 {result.trace.llm_calls} 次
            <span className="mx-2 text-indigo-300">·</span>
            {result.trace.token_usage.total_tokens.toLocaleString()} tokens
          </div>
        )}
      </header>

      <section className="panel">
        <div className="grid gap-5 lg:grid-cols-[1fr_auto] lg:items-end">
          <div>
            <label className="text-sm font-medium text-slate-700" htmlFor="ranking-resume">
              排名使用的简历
            </label>
            <select
              className="mt-2 w-full rounded-xl border border-slate-200 bg-white px-4 py-3 outline-none transition focus:border-indigo-500 focus:ring-4 focus:ring-indigo-100"
              id="ranking-resume"
              onChange={(event) => setResumeId(event.target.value)}
              value={resumeId}
            >
              {resumes.length === 0 && <option value="">暂无可用简历</option>}
              {resumes.map((resume) => (
                <option key={resume.id} value={resume.id}>
                  {resume.name}{resume.is_default ? "（默认）" : ""}
                </option>
              ))}
            </select>
          </div>
          <button
            className="rounded-xl bg-indigo-600 px-6 py-3 font-medium text-white transition hover:bg-indigo-700 disabled:cursor-not-allowed disabled:opacity-50"
            disabled={loading || !resumeId}
            onClick={() => void handleRank()}
            type="button"
          >
            {loading ? "正在运行五阶段排名…" : "运行 Ranking Pipeline"}
          </button>
        </div>
        {resumes.length === 0 && (
          <p className="mt-4 text-sm text-amber-700">
            请先到 <Link className="font-medium underline" href="/resume">简历管理</Link> 上传并解析简历。
          </p>
        )}
      </section>

      {error && <div className="rounded-xl border border-rose-200 bg-rose-50 p-4 text-rose-800">{error}</div>}

      {result && (
        <>
          <section className="panel">
            <div className="flex flex-wrap items-center justify-between gap-3">
              <div>
                <p className="eyebrow">Pipeline Trace</p>
                <h2 className="mt-2 text-xl font-semibold">候选收敛漏斗</h2>
              </div>
              <p className="text-sm text-slate-500">Run ID: {result.trace.run_id}</p>
            </div>
            <div className="mt-6 grid gap-3 md:grid-cols-5">
              {result.trace.stages.map((stage, index) => (
                <div className="relative rounded-2xl bg-slate-50 p-4" key={stage.name}>
                  <p className="text-xs font-semibold uppercase tracking-wider text-indigo-600">0{index + 1}</p>
                  <p className="mt-3 text-sm font-semibold">{stageLabels[stage.name]}</p>
                  <p className="mt-3 text-2xl font-semibold text-slate-900">
                    {stage.input_count}<span className="mx-1 text-base text-slate-300">→</span>{stage.output_count}
                  </p>
                  <p className="mt-1 text-xs text-slate-400">{stage.duration_ms.toFixed(2)} ms</p>
                </div>
              ))}
            </div>
            <div className="mt-5 flex flex-wrap gap-2 text-xs text-slate-500">
              <span className="rounded-full bg-slate-100 px-3 py-1">候选上限 {result.trace.config.candidate_limit}</span>
              <span className="rounded-full bg-slate-100 px-3 py-1">Embedding Top {result.trace.config.top_k_embedding}</span>
              <span className="rounded-full bg-slate-100 px-3 py-1">Rerank Top {result.trace.config.top_k_rerank}</span>
              <span className="rounded-full bg-slate-100 px-3 py-1">LLM Top {result.trace.config.top_k_llm}</span>
              <span className="rounded-full bg-slate-100 px-3 py-1">Final Top {result.trace.config.final_top_k}</span>
            </div>
          </section>

          <section>
            <div className="mb-4 flex items-end justify-between gap-4">
              <div>
                <p className="eyebrow">Final Ranking</p>
                <h2 className="mt-2 text-xl font-semibold">推荐职位</h2>
              </div>
              <p className="text-sm text-slate-500">共处理 {result.total_candidates} 个候选</p>
            </div>
            {result.items.length === 0 && (
              <div className="panel text-center text-slate-500">当前没有通过所有阶段的职位。</div>
            )}
            <div className="grid gap-4">
              {result.items.map((item) => (
                <article className="panel" key={item.job.id}>
                  <div className="flex flex-wrap items-start justify-between gap-5">
                    <div className="flex gap-4">
                      <span className="grid h-11 w-11 shrink-0 place-items-center rounded-xl bg-indigo-600 font-semibold text-white">#{item.rank}</span>
                      <div>
                        <Link className="text-lg font-semibold text-indigo-700 hover:text-indigo-900" href={`/jobs/${item.job.id}`}>
                          {item.job.title}
                        </Link>
                        <p className="mt-1 text-sm text-slate-500">{item.job.location ?? "地点未注明"} · {item.job.platform}</p>
                        <p className="mt-3 max-w-3xl text-sm leading-6 text-slate-600">{item.score.reasoning_summary}</p>
                      </div>
                    </div>
                    <div className="text-right">
                      <p className="text-3xl font-semibold text-slate-900">{item.score.final_score.toFixed(1)}</p>
                      <p className="mt-1 text-xs uppercase tracking-wider text-slate-400">Final Score</p>
                      <span className="mt-3 inline-block rounded-full bg-emerald-50 px-3 py-1 text-xs font-medium text-emerald-700">
                        {recommendationLabels[item.score.recommendation]}
                      </span>
                    </div>
                  </div>
                  <div className="mt-5 grid grid-cols-3 gap-2 border-t border-slate-100 pt-4 text-center sm:grid-cols-6">
                    {[
                      ["语义", item.score.semantic_score],
                      ["技能", item.score.skill_score],
                      ["学历", item.score.education_score],
                      ["经验", item.score.experience_score],
                      ["偏好", item.score.preference_score],
                      ["LLM", item.score.llm_score],
                    ].map(([label, score]) => (
                      <div key={String(label)}>
                        <p className="text-xs text-slate-400">{label}</p>
                        <p className="mt-1 font-semibold">{Number(score).toFixed(1)}</p>
                      </div>
                    ))}
                  </div>
                </article>
              ))}
            </div>
          </section>

          <section className="panel">
            <p className="eyebrow">Full Trace</p>
            <h2 className="mt-2 text-xl font-semibold">逐阶段决策明细</h2>
            <div className="mt-5 divide-y divide-slate-100">
              {result.trace.stages.map((stage) => (
                <details className="group py-4" key={stage.name}>
                  <summary className="flex cursor-pointer list-none items-center justify-between gap-4 font-medium">
                    <span>{stageLabels[stage.name]}</span>
                    <span className="text-sm font-normal text-slate-500">{stage.input_count} 入场 · {stage.output_count} 晋级</span>
                  </summary>
                  <div className="mt-4 overflow-x-auto rounded-xl border border-slate-200">
                    <table className="w-full min-w-[720px] text-left text-sm">
                      <thead className="bg-slate-50 text-slate-500">
                        <tr>
                          <th className="px-4 py-3 font-medium">阶段排名</th>
                          <th className="px-4 py-3 font-medium">职位</th>
                          <th className="px-4 py-3 font-medium">阶段分数</th>
                          <th className="px-4 py-3 font-medium">语义 / 技能 / LLM</th>
                          <th className="px-4 py-3 font-medium">决策</th>
                        </tr>
                      </thead>
                      <tbody className="divide-y divide-slate-100">
                        {stage.candidates.map((candidate) => (
                          <tr key={candidate.job_id}>
                            <td className="px-4 py-3 text-slate-500">#{candidate.rank ?? "—"}</td>
                            <td className="px-4 py-3 font-medium">{candidate.title}</td>
                            <td className="px-4 py-3">{candidate.score?.toFixed(2) ?? "规则判断"}</td>
                            <td className="px-4 py-3 text-slate-500">
                              {(candidate.sub_scores.semantic ?? 0).toFixed(1)} / {(candidate.sub_scores.skill ?? 0).toFixed(1)} / {candidate.recommendation ? candidate.score?.toFixed(1) ?? "—" : "—"}
                            </td>
                            <td className="px-4 py-3">
                              <span className={`rounded-full px-3 py-1 text-xs font-medium ${candidate.selected ? "bg-emerald-50 text-emerald-700" : "bg-slate-100 text-slate-500"}`}>
                                {candidate.selected ? "晋级" : "淘汰"}
                              </span>
                              {candidate.reasons.length > 0 && <p className="mt-2 max-w-xs text-xs text-rose-600">{candidate.reasons.join("；")}</p>}
                            </td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                </details>
              ))}
            </div>
          </section>
        </>
      )}
    </div>
  );
}
