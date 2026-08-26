"use client";

import Link from "next/link";
import { useEffect, useState } from "react";

import {
  getJobRankingResult,
  getJobRankingRun,
  getResumes,
  startJobRanking,
  type JobRankingResponse,
  type RankingRun,
  type RankingScoringMode,
  type RankingStageName,
  type Resume,
} from "../../lib/api";

const stageLabels: Record<RankingStageName, string> = {
  rule_filter: "Rule Filter",
  embedding_rank: "Embedding Rank",
  reranker: "Reranker",
  llm_judge: "LLM Judge",
  deterministic_rank: "快速综合评分",
  final_ranking: "Final Ranking",
};

const recommendationLabels = {
  strong_apply: "强烈建议",
  apply: "建议投递",
  maybe: "可以考虑",
  skip: "暂时跳过",
};

const RANKING_RUN_STORAGE_KEY = "careerpilot-ranking-run-id";
const RANKING_MODE_STORAGE_KEY = "careerpilot-ranking-mode";

const progressStageLabels: Record<string, string> = {
  queued: "等待执行",
  loading_candidates: "加载并解析候选职位",
  rule_filter: "规则筛选",
  embedding_rank: "向量召回",
  reranker: "精排计算",
  llm_judge: "LLM 深度评分",
  deterministic_rank: "快速综合评分（不调用 LLM）",
  final_ranking: "生成最终排名",
  completed: "排名完成",
  failed: "排名失败",
  interrupted: "任务中断",
};

export default function RankingPage() {
  const [resumes, setResumes] = useState<Resume[]>([]);
  const [resumeId, setResumeId] = useState("");
  const [result, setResult] = useState<JobRankingResponse | null>(null);
  const [run, setRun] = useState<RankingRun | null>(null);
  const [scoringMode, setScoringMode] = useState<RankingScoringMode>("fast");
  const [deepLimit, setDeepLimit] = useState(10);
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

  useEffect(() => {
    const storedRunId = window.localStorage.getItem(RANKING_RUN_STORAGE_KEY);
    if (!storedRunId) return;
    const storedMode = window.localStorage.getItem(RANKING_MODE_STORAGE_KEY);
    if (storedMode === "fast" || storedMode === "llm") setScoringMode(storedMode);
    let cancelled = false;

    async function restoreRun() {
      try {
        const storedRun = await getJobRankingRun(storedRunId as string);
        if (cancelled) return;
        setRun(storedRun);
        if (storedRun.status === "SUCCEEDED") {
          const storedResult = await getJobRankingResult(storedRun.id);
          if (!cancelled) {
            setResult(storedResult);
            setScoringMode(storedResult.trace.config.scoring_mode);
          }
        } else if (["PENDING", "RUNNING"].includes(storedRun.status)) {
          setLoading(true);
        } else if (storedRun.error) {
          setError(storedRun.error);
        }
      } catch {
        window.localStorage.removeItem(RANKING_RUN_STORAGE_KEY);
      }
    }

    void restoreRun();
    return () => { cancelled = true; };
  }, []);

  const pollingRunId = run && ["PENDING", "RUNNING"].includes(run.status) ? run.id : null;

  useEffect(() => {
    if (!pollingRunId) return;
    const activeRunId: string = pollingRunId;
    let cancelled = false;

    async function poll() {
      while (!cancelled) {
        await new Promise((resolve) => window.setTimeout(resolve, 1200));
        if (cancelled) return;
        try {
          const nextRun = await getJobRankingRun(activeRunId);
          if (cancelled) return;
          if (nextRun.status === "SUCCEEDED") {
            const nextResult = await getJobRankingResult(nextRun.id);
            if (!cancelled) {
              setRun(nextRun);
              setResult(nextResult);
              setScoringMode(nextResult.trace.config.scoring_mode);
              setLoading(false);
            }
            return;
          }
          if (nextRun.status === "FAILED") {
            setRun(nextRun);
            setError(nextRun.error || "职位排名任务执行失败。");
            setLoading(false);
            window.localStorage.removeItem(RANKING_RUN_STORAGE_KEY);
            return;
          }
          setRun(nextRun);
        } catch (reason) {
          if (!cancelled) {
            setError(reason instanceof Error ? reason.message : "无法读取排名任务状态。");
            setLoading(false);
          }
          return;
        }
      }
    }

    void poll();
    return () => { cancelled = true; };
  }, [pollingRunId]);

  async function handleRank() {
    setLoading(true);
    setError(null);
    setResult(null);
    try {
      const startedRun = await startJobRanking(resumeId || undefined, {
        scoringMode,
        deepLimit,
      });
      window.localStorage.setItem(RANKING_RUN_STORAGE_KEY, startedRun.id);
      window.localStorage.setItem(RANKING_MODE_STORAGE_KEY, scoringMode);
      setRun(startedRun);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "职位排名失败。");
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
            快速模式完全不调用 LLM；深度模式仅让少量高潜力职位进入 LLM 复核，并复用已完成评分缓存。
          </p>
        </div>
        {result && (
          <div className="ranking-meta rounded-2xl px-5 py-3 text-sm">
            <span className="font-semibold">{result.trace.version}</span>
            <span className="mx-2 opacity-60">·</span>
            {result.trace.config.scoring_mode === "fast" ? "快速评分 · 未调用 LLM" : `LLM 调用 ${result.trace.llm_calls} 次`}
            <span className="mx-2 opacity-60">·</span>
            缓存命中 {result.trace.cache_hits} 个
            {result.trace.config.scoring_mode === "llm" && <><span className="mx-2 opacity-60">·</span>{result.trace.token_usage.total_tokens.toLocaleString()} tokens</>}
          </div>
        )}
      </header>

      <section className="panel">
        <div className="grid gap-5 lg:grid-cols-[1fr_1.4fr_auto] lg:items-end">
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
          <div>
            <p className="text-sm font-medium text-slate-700">评分模式</p>
            <div className="mt-2 grid gap-2 sm:grid-cols-2">
              {([
                ["fast", "快速评分", "不调用 LLM，通常数秒完成"],
                ["llm", "LLM 深度评分", "对高潜职位进行模型复核"],
              ] as const).map(([mode, label, description]) => (
                <button
                  aria-pressed={scoringMode === mode}
                  className={`rounded-xl border px-4 py-3 text-left transition ${scoringMode === mode ? "border-indigo-500 bg-indigo-50 text-indigo-900 ring-2 ring-indigo-100" : "border-slate-200 bg-white text-slate-600 hover:border-indigo-300"}`}
                  key={mode}
                  onClick={() => setScoringMode(mode)}
                  type="button"
                >
                  <span className="block text-sm font-semibold">{label}{mode === "fast" ? "（推荐）" : ""}</span>
                  <span className="mt-1 block text-xs opacity-75">{description}</span>
                </button>
              ))}
            </div>
          </div>
          <button
            className="rounded-xl bg-indigo-600 px-6 py-3 font-medium text-white transition hover:bg-indigo-700 disabled:cursor-not-allowed disabled:opacity-50"
            disabled={loading || !resumeId}
            onClick={() => void handleRank()}
            type="button"
          >
            {loading ? "正在智能排名…" : scoringMode === "fast" ? "开始快速排名" : "开始深度排名"}
          </button>
        </div>
        {scoringMode === "llm" && (
          <div className="mt-5 max-w-sm">
            <label className="text-sm font-medium text-slate-700" htmlFor="ranking-deep-limit">LLM 深评职位数量</label>
            <select
              className="mt-2 w-full rounded-xl border border-slate-200 bg-white px-4 py-3 outline-none transition focus:border-indigo-500 focus:ring-4 focus:ring-indigo-100"
              id="ranking-deep-limit"
              onChange={(event) => setDeepLimit(Number(event.target.value))}
              value={deepLimit}
            >
              <option value={5}>5 个（更快）</option>
              <option value={10}>10 个（推荐）</option>
              <option value={15}>15 个</option>
              <option value={30}>30 个（较慢）</option>
            </select>
            <p className="mt-2 text-xs text-slate-500">数量越少，LLM 调用越少；已缓存的职位不会重复调用。</p>
          </div>
        )}
        {run && (
          <div className="ranking-surface-muted mt-5 rounded-2xl p-4">
            <div className="flex flex-wrap items-center justify-between gap-3 text-sm">
              <div>
                <span className="ranking-main-text font-medium">
                  {progressStageLabels[run.stage] ?? run.stage}
                </span>
                <span className="ranking-muted-text ml-2">{run.progress}%</span>
              </div>
              <div className="ranking-muted-text flex flex-wrap gap-x-4 gap-y-1 text-xs">
                <span>已处理 {run.processed_candidates}/{run.total_candidates || "—"}</span>
                <span>缓存命中 {run.cache_hits}</span>
                {scoringMode === "llm" && <span>LLM 调用 {run.llm_calls}</span>}
                {run.fallback_count > 0 && <span className="ranking-warning-text">降级评分 {run.fallback_count}</span>}
              </div>
            </div>
            <div className="ranking-progress-track mt-3 h-2 overflow-hidden rounded-full">
              <div
                className="h-full rounded-full bg-indigo-600 transition-[width] duration-300"
                style={{ width: `${run.progress}%` }}
              />
            </div>
            <p className="ranking-faint-text mt-3 text-xs">
              {scoringMode === "fast" ? "快速模式只使用本地规则、语义和简历匹配信号。" : "排名在后台执行；已完成的 LLM 评分会直接复用。"}
            </p>
          </div>
        )}
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
                <div className="ranking-surface-muted relative rounded-2xl p-4" key={stage.name}>
                  <p className="ranking-accent-text text-xs font-semibold uppercase tracking-wider">0{index + 1}</p>
                  <p className="ranking-main-text mt-3 text-sm font-semibold">{stageLabels[stage.name]}</p>
                  <p className="ranking-main-text mt-3 text-2xl font-semibold">
                    {stage.input_count}<span className="ranking-faint-text mx-1 text-base">→</span>{stage.output_count}
                  </p>
                  <p className="ranking-faint-text mt-1 text-xs">{stage.duration_ms.toFixed(2)} ms</p>
                </div>
              ))}
            </div>
            <div className="mt-5 flex flex-wrap gap-2 text-xs text-slate-500">
              <span className="ranking-tag rounded-full px-3 py-1">候选上限 {result.trace.config.candidate_limit}</span>
              <span className="ranking-tag rounded-full px-3 py-1">Embedding Top {result.trace.config.top_k_embedding}</span>
              <span className="ranking-tag rounded-full px-3 py-1">Rerank Top {result.trace.config.top_k_rerank}</span>
              <span className="ranking-tag rounded-full px-3 py-1">{result.trace.config.scoring_mode === "fast" ? `快速综合 Top ${result.trace.config.top_k_llm}` : `LLM Top ${result.trace.config.top_k_llm}`}</span>
              <span className="ranking-tag rounded-full px-3 py-1">Final Top {result.trace.config.final_top_k}</span>
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
                <article className="ranking-result-card panel" key={item.job.id}>
                  <div className="flex flex-wrap items-start justify-between gap-5">
                    <div className="flex gap-4">
                      <span className="grid h-11 w-11 shrink-0 place-items-center rounded-xl bg-indigo-600 font-semibold text-white">#{item.rank}</span>
                      <div>
                        <Link className="ranking-link text-lg font-semibold hover:underline" href={`/jobs/${item.job.id}`}>
                          {item.job.title}
                        </Link>
                        <p className="ranking-muted-text mt-1 text-sm">{item.job.location ?? "地点未注明"} · {item.job.platform}</p>
                        <p className="ranking-muted-text mt-3 max-w-3xl text-sm leading-6">{item.score.reasoning_summary}</p>
                      </div>
                    </div>
                    <div className="text-right">
                      <p className="ranking-main-text text-3xl font-semibold">{item.score.final_score.toFixed(1)}</p>
                      <p className="ranking-faint-text mt-1 text-xs uppercase tracking-wider">Final Score</p>
                      <span className="ranking-success-pill mt-3 inline-block rounded-full px-3 py-1 text-xs font-medium">
                        {recommendationLabels[item.score.recommendation]}
                      </span>
                    </div>
                  </div>
                  <div className={`ranking-divider mt-5 grid grid-cols-3 gap-2 border-t pt-4 text-center ${result.trace.config.scoring_mode === "fast" ? "sm:grid-cols-5" : "sm:grid-cols-6"}`}>
                    {[
                      ["语义", item.score.semantic_score],
                      ["技能", item.score.skill_score],
                      ["学历", item.score.education_score],
                      ["经验", item.score.experience_score],
                      ["偏好", item.score.preference_score],
                      ...(result.trace.config.scoring_mode === "llm" ? [["LLM", item.score.llm_score] as [string, number]] : []),
                    ].map(([label, score]) => (
                      <div key={String(label)}>
                        <p className="ranking-faint-text text-xs">{label}</p>
                        <p className="ranking-main-text mt-1 font-semibold">{Number(score).toFixed(1)}</p>
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
            <div className="ranking-divider mt-5 divide-y">
              {result.trace.stages.map((stage) => (
                <details className="group py-4" key={stage.name}>
                  <summary className="flex cursor-pointer list-none items-center justify-between gap-4 font-medium">
                    <span>{stageLabels[stage.name]}</span>
                    <span className="ranking-muted-text text-sm font-normal">{stage.input_count} 入场 · {stage.output_count} 晋级</span>
                  </summary>
                  <div className="ranking-border mt-4 overflow-x-auto rounded-xl border">
                    <table className="w-full min-w-[720px] text-left text-sm">
                      <thead className="ranking-surface-muted ranking-muted-text">
                        <tr>
                          <th className="px-4 py-3 font-medium">阶段排名</th>
                          <th className="px-4 py-3 font-medium">职位</th>
                          <th className="px-4 py-3 font-medium">阶段分数</th>
                          <th className="px-4 py-3 font-medium">{result.trace.config.scoring_mode === "fast" ? "语义 / 技能" : "语义 / 技能 / LLM"}</th>
                          <th className="px-4 py-3 font-medium">决策</th>
                        </tr>
                      </thead>
                      <tbody className="divide-y divide-slate-100">
                        {stage.candidates.map((candidate) => (
                          <tr key={candidate.job_id}>
                            <td className="ranking-muted-text px-4 py-3">#{candidate.rank ?? "—"}</td>
                            <td className="ranking-main-text px-4 py-3 font-medium">{candidate.title}</td>
                            <td className="ranking-main-text px-4 py-3">{candidate.score?.toFixed(2) ?? "规则判断"}</td>
                            <td className="ranking-muted-text px-4 py-3">
                              {(candidate.sub_scores.semantic ?? 0).toFixed(1)} / {(candidate.sub_scores.skill ?? 0).toFixed(1)}{result.trace.config.scoring_mode === "llm" ? ` / ${candidate.recommendation ? candidate.score?.toFixed(1) ?? "—" : "—"}` : ""}
                            </td>
                            <td className="px-4 py-3">
                              <span className={`rounded-full px-3 py-1 text-xs font-medium ${candidate.selected ? "ranking-success-pill" : "ranking-tag"}`}>
                                {candidate.selected ? "晋级" : "淘汰"}
                              </span>
                              {candidate.reasons.length > 0 && <p className="ranking-danger-text mt-2 max-w-xs text-xs">{candidate.reasons.join("；")}</p>}
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
