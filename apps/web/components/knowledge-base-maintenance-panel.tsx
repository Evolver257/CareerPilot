"use client";

import { useCallback, useEffect, useState } from "react";

import {
  createKnowledgeIndexRun,
  getKnowledgeHealth,
  type KnowledgeHealth,
} from "../lib/api";

function statusLabel(status: KnowledgeHealth["status"] | undefined) {
  if (status === "ready") return "可用";
  if (status === "needs_update") return "需要更新";
  if (status === "partial") return "部分可用";
  return "尚未构建";
}

export function KnowledgeBaseMaintenancePanel() {
  const [health, setHealth] = useState<KnowledgeHealth | null>(null);
  const [run, setRun] = useState<KnowledgeHealth["latest_run"]>(null);
  const [loading, setLoading] = useState(true);
  const [starting, setStarting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async (showLoading = false) => {
    if (showLoading) setLoading(true);
    try {
      const response = await getKnowledgeHealth();
      setHealth(response);
      setRun(response.latest_run);
      setError(null);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "无法读取岗位知识库状态");
    } finally {
      if (showLoading) setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load(true);
  }, [load]);

  const runId = run?.id;
  const runStatus = run?.status;

  useEffect(() => {
    if (!runId || !runStatus || !["PENDING", "RUNNING"].includes(runStatus)) return;
    let current = true;
    let pending = false;
    const timer = window.setInterval(() => {
      if (pending) return;
      pending = true;
      getKnowledgeHealth()
        .then((response) => {
          if (!current) return;
          setHealth(response);
          setRun(response.latest_run);
          setError(null);
        })
        .catch((reason) => {
          if (current) {
            setError(reason instanceof Error ? reason.message : "无法刷新知识库任务进度");
          }
        })
        .finally(() => {
          pending = false;
        });
    }, 3000);
    return () => {
      current = false;
      window.clearInterval(timer);
    };
  }, [runId, runStatus]);

  async function start(mode: "incremental" | "backfill") {
    if (starting || (run && ["PENDING", "RUNNING"].includes(run.status))) return;
    setStarting(true);
    setError(null);
    try {
      const created = await createKnowledgeIndexRun({ mode, auto_start: true });
      setRun(created);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "无法启动知识库维护任务");
    } finally {
      setStarting(false);
    }
  }

  const status = health?.status ?? "not_built";
  const active = Boolean(run && ["PENDING", "RUNNING"].includes(run.status));
  const needsUpdate = health?.needs_update_jobs
    ?? Math.max(0, (health?.jobs_total ?? 0) - (health?.indexed_jobs ?? 0));
  const primaryMode = status === "not_built" ? "backfill" : "incremental";
  const primaryLabel = status === "not_built"
    ? "开始全量构建"
    : needsUpdate > 0
      ? `更新 ${needsUpdate} 个岗位`
      : "检查增量更新";

  return (
    <section aria-label="岗位知识库维护" className="panel">
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div>
          <p className="eyebrow">数据与索引</p>
          <h2 className="mt-2 text-xl font-semibold text-slate-900 dark:text-slate-100">岗位知识库</h2>
          <p className="mt-2 max-w-2xl text-sm leading-6 text-slate-500 dark:text-slate-400">
            维护岗位 JD 的知识片段与向量索引。新岗位会自动进入增量队列，这里用于查看状态、补齐历史数据和处理失败任务。
          </p>
        </div>
        <div className="flex items-center gap-2">
          <span className={`rounded-full px-3 py-1.5 text-xs font-semibold ${status === "ready" ? "bg-emerald-50 text-emerald-700 dark:bg-emerald-950/40 dark:text-emerald-300" : status === "not_built" ? "bg-amber-50 text-amber-700 dark:bg-amber-950/40 dark:text-amber-300" : "bg-indigo-50 text-indigo-700 dark:bg-indigo-950/40 dark:text-indigo-300"}`}>
            {loading ? "读取中…" : statusLabel(status)}
          </span>
          <button className="rounded-lg border border-slate-200 px-3 py-1.5 text-xs font-medium text-slate-600 transition hover:border-indigo-300 hover:text-indigo-700 disabled:opacity-50 dark:border-slate-700 dark:text-slate-300 dark:hover:border-indigo-500 dark:hover:text-indigo-300" disabled={loading} onClick={() => void load(true)} type="button">
            刷新
          </button>
        </div>
      </div>

      {error && <div className="mt-5 rounded-xl border border-rose-200 bg-rose-50 px-4 py-3 text-sm text-rose-700 dark:border-rose-900/60 dark:bg-rose-950/30 dark:text-rose-300">{error}</div>}

      {loading ? (
        <div aria-label="正在加载岗位知识库状态" className="mt-5 h-24 animate-pulse rounded-2xl bg-slate-100 dark:bg-slate-800" />
      ) : health ? (
        <>
          <dl className="mt-5 grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
            <div className="rounded-xl border border-slate-200 bg-slate-50 p-4 dark:border-slate-700 dark:bg-slate-900/60"><dt className="text-xs text-slate-500 dark:text-slate-400">已索引岗位</dt><dd className="mt-2 text-xl font-semibold text-slate-900 dark:text-slate-100">{health.compatible_jobs ?? health.indexed_jobs}<span className="ml-1 text-sm font-normal text-slate-400">/ {health.jobs_total}</span></dd></div>
            <div className="rounded-xl border border-slate-200 bg-slate-50 p-4 dark:border-slate-700 dark:bg-slate-900/60"><dt className="text-xs text-slate-500 dark:text-slate-400">知识片段</dt><dd className="mt-2 text-xl font-semibold text-slate-900 dark:text-slate-100">{health.chunk_count}</dd></div>
            <div className="rounded-xl border border-slate-200 bg-slate-50 p-4 dark:border-slate-700 dark:bg-slate-900/60"><dt className="text-xs text-slate-500 dark:text-slate-400">有效向量</dt><dd className="mt-2 text-xl font-semibold text-slate-900 dark:text-slate-100">{health.embedded_chunk_count ?? health.chunk_count}</dd></div>
            <div className="rounded-xl border border-slate-200 bg-slate-50 p-4 dark:border-slate-700 dark:bg-slate-900/60"><dt className="text-xs text-slate-500 dark:text-slate-400">Embedding</dt><dd className="mt-2 truncate text-sm font-semibold text-slate-900 dark:text-slate-100" title={health.embedding_model ?? "未配置"}>{health.embedding_model ?? "未配置"}</dd></div>
          </dl>

          {run && ["PENDING", "RUNNING"].includes(run.status) && (
            <div className="mt-5 rounded-xl border border-indigo-200 bg-indigo-50 p-4 text-sm text-indigo-800 dark:border-indigo-900/60 dark:bg-indigo-950/30 dark:text-indigo-200">
              <div className="flex flex-wrap items-center justify-between gap-2"><span className="font-semibold">知识库正在更新</span><span>{run.progress}% · {run.processed_jobs}/{run.total_jobs} 个岗位</span></div>
              <div className="mt-3 h-2 overflow-hidden rounded-full bg-indigo-100 dark:bg-indigo-950"><div className="h-full rounded-full bg-indigo-600 transition-[width] duration-500 dark:bg-indigo-400" style={{ width: `${run.progress}%` }} /></div>
            </div>
          )}

          {run?.status === "FAILED" && (
            <div className="mt-5 rounded-xl border border-rose-200 bg-rose-50 p-4 text-sm text-rose-700 dark:border-rose-900/60 dark:bg-rose-950/30 dark:text-rose-300">
              <p className="font-semibold">上次维护失败</p><p className="mt-1 text-xs leading-5">{run.error ?? "请重试维护任务。"}</p>
            </div>
          )}

          {status === "not_built" && !active && (
            <p className="mt-5 rounded-xl border border-amber-200 bg-amber-50 px-4 py-3 text-sm text-amber-800 dark:border-amber-900/60 dark:bg-amber-950/30 dark:text-amber-300">知识库尚未构建。完成全量构建后，职业顾问才能引用岗位 JD 回答。</p>
          )}

          <div className="mt-5 flex flex-wrap items-center gap-3">
            <button className="rounded-xl bg-indigo-600 px-4 py-2.5 text-sm font-semibold text-white transition hover:bg-indigo-700 disabled:cursor-not-allowed disabled:opacity-50 dark:bg-indigo-500 dark:hover:bg-indigo-400" disabled={starting || active} onClick={() => void start(primaryMode)} type="button">
              {starting ? "启动中…" : active ? "更新进行中" : run?.status === "FAILED" ? "重试维护" : primaryLabel}
            </button>
            {status !== "not_built" && <button className="rounded-xl border border-slate-200 px-4 py-2.5 text-sm font-medium text-slate-600 transition hover:border-indigo-300 hover:text-indigo-700 disabled:cursor-not-allowed disabled:opacity-50 dark:border-slate-700 dark:text-slate-300 dark:hover:border-indigo-500 dark:hover:text-indigo-300" disabled={starting || active} onClick={() => void start("backfill")} type="button">全量回填</button>}
            {health.updated_at && <span className="text-xs text-slate-400 dark:text-slate-500">最近更新：{new Date(health.updated_at).toLocaleString("zh-CN")}</span>}
          </div>
        </>
      ) : null}
    </section>
  );
}
