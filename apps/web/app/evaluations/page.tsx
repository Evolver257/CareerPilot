"use client";

import { useEffect, useMemo, useState } from "react";

import {
  compareEvaluationRuns,
  createEvaluationRun,
  getEvaluationDatasets,
  getEvaluationRun,
  getEvaluationRuns,
  importToolEvaluationSeed,
  updateEvaluationRun,
  type EvaluationDataset,
  type EvaluationRun,
} from "../../lib/api";

const terminal = new Set(["SUCCEEDED", "FAILED", "CANCELLED", "TIMED_OUT"]);

function summary(run: EvaluationRun): Record<string, unknown> {
  const value = run.result.summary;
  return value && typeof value === "object" ? value as Record<string, unknown> : {};
}

function isNonGoldRun(run: EvaluationRun, datasets: EvaluationDataset[]): boolean {
  const metadata = run.result.evaluation_metadata;
  if (metadata && typeof metadata === "object" && "quality_claim_allowed" in metadata) {
    return (metadata as Record<string, unknown>).quality_claim_allowed !== true;
  }
  return datasets.find((dataset) => dataset.id === run.dataset_id)?.label_status !== "adjudicated_gold";
}

function failedCases(run: EvaluationRun): Array<Record<string, unknown>> {
  const rows = run.result.cases;
  if (!Array.isArray(rows)) return [];
  return rows.filter((value): value is Record<string, unknown> => {
    if (!value || typeof value !== "object") return false;
    const row = value as Record<string, unknown>;
    return Boolean(
      row.error
      || row.task_completed === false
      || row.exact_sequence_success === false
      || row.forbidden_tool_violation === true
      || Number(row.invalid_call_rate ?? 0) > 0
      || Number(row.recall ?? 1) < 1
      || Number(row.no_answer_accuracy ?? 1) < 1
      || Number(row.faithfulness ?? 1) < 1
      || Number(row.citation_correctness ?? 1) < 1
      || Number(row.unsupported_answer ?? 0) > 0,
    );
  });
}

function download(run: EvaluationRun, format: "json" | "csv" | "md") {
  const metrics = summary(run);
  let body = JSON.stringify(run, null, 2);
  let mime = "application/json";
  if (format === "csv") {
    body = `metric,value\n${Object.entries(metrics).map(([key, value]) => `${JSON.stringify(key)},${JSON.stringify(value)}`).join("\n")}`;
    mime = "text/csv";
  } else if (format === "md") {
    body = `# CareerPilot Evaluation ${run.id}\n\n|Metric|Value|\n|---|---:|\n${Object.entries(metrics).map(([key, value]) => `|${key}|${String(value)}|`).join("\n")}`;
    mime = "text/markdown";
  }
  const url = URL.createObjectURL(new Blob([body], { type: mime }));
  const anchor = document.createElement("a");
  anchor.href = url; anchor.download = `evaluation-${run.id}.${format}`; anchor.click();
  URL.revokeObjectURL(url);
}

export default function EvaluationsPage() {
  const [datasets, setDatasets] = useState<EvaluationDataset[]>([]);
  const [runs, setRuns] = useState<EvaluationRun[]>([]);
  const [datasetId, setDatasetId] = useState("");
  const [observations, setObservations] = useState("[]");
  const [model, setModel] = useState("当前 Provider");
  const [promptVersion, setPromptVersion] = useState("career-advisor-v2");
  const [finalTopK, setFinalTopK] = useState(10);
  const [chunkSize, setChunkSize] = useState(256);
  const [chunkOverlap, setChunkOverlap] = useState(32);
  const [denseTopK, setDenseTopK] = useState(30);
  const [sparseTopK, setSparseTopK] = useState(30);
  const [rrfK, setRrfK] = useState(60);
  const [denseWeight, setDenseWeight] = useState(0.45);
  const [minimumRelevance, setMinimumRelevance] = useState(0.42);
  const [rerankerEnabled, setRerankerEnabled] = useState(true);
  const [queryRewrite, setQueryRewrite] = useState(true);
  const [metadataFilter, setMetadataFilter] = useState(true);
  const [requireGold, setRequireGold] = useState(false);
  const [selectedRun, setSelectedRun] = useState<string | null>(null);
  const [leftId, setLeftId] = useState("");
  const [rightId, setRightId] = useState("");
  const [delta, setDelta] = useState<Record<string, number>>({});
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const active = useMemo(() => runs.find((run) => run.id === selectedRun) ?? runs[0], [runs, selectedRun]);

  async function load() {
    const [nextDatasets, nextRuns] = await Promise.all([getEvaluationDatasets(), getEvaluationRuns()]);
    setDatasets(nextDatasets); setRuns(nextRuns);
    setDatasetId((current) => current || nextDatasets[0]?.id || "");
  }

  useEffect(() => { void load().catch((reason) => setError(reason instanceof Error ? reason.message : "评测数据加载失败")); }, []);

  useEffect(() => {
    const running = runs.filter((run) => !terminal.has(run.status));
    if (!running.length) return;
    const timer = window.setInterval(() => {
      void Promise.all(running.map((run) => getEvaluationRun(run.id))).then((fresh) => {
        setRuns((current) => current.map((run) => fresh.find((item) => item.id === run.id) ?? run));
      });
    }, 1500);
    return () => window.clearInterval(timer);
  }, [runs]);

  async function importSeed() {
    setBusy(true); setError(null);
    try { const item = await importToolEvaluationSeed(); await load(); setDatasetId(item.id); }
    catch (reason) { setError(reason instanceof Error ? reason.message : "种子集导入失败"); }
    finally { setBusy(false); }
  }

  async function start() {
    setBusy(true); setError(null);
    try {
      const parsed = JSON.parse(observations) as Array<Record<string, unknown>>;
      if (!Array.isArray(parsed)) throw new Error("Observations 必须是 JSON 数组");
      const run = await createEvaluationRun({
        dataset_id: datasetId,
        observations: parsed,
        configuration: {
          model,
          prompt_version: promptVersion,
          chunk_size: chunkSize,
          chunk_overlap: chunkOverlap,
          dense_top_k: denseTopK,
          sparse_top_k: sparseTopK,
          final_top_k: finalTopK,
          rrf_k: rrfK,
          dense_weight: denseWeight,
          sparse_weight: Number((1 - denseWeight).toFixed(2)),
          minimum_relevance: minimumRelevance,
          reranker_enabled: rerankerEnabled,
          query_rewrite: queryRewrite,
          metadata_filter: metadataFilter,
          seed: 20260907,
        },
        require_gold: requireGold,
      });
      setRuns((current) => [run, ...current]); setSelectedRun(run.id);
    } catch (reason) { setError(reason instanceof Error ? reason.message : "评测启动失败"); }
    finally { setBusy(false); }
  }

  async function action(run: EvaluationRun, name: "cancel" | "retry") {
    setBusy(true); setError(null);
    try { const next = await updateEvaluationRun(run.id, name); setRuns((current) => current.map((item) => item.id === next.id ? next : item)); }
    catch (reason) { setError(reason instanceof Error ? reason.message : "评测操作失败"); }
    finally { setBusy(false); }
  }

  return <div className="mx-auto max-w-6xl space-y-6">
    <header><p className="eyebrow">开发 / 管理员</p><h1 className="mt-2 text-3xl font-semibold">Agent 评测控制台</h1><p className="mt-2 text-sm text-slate-500">该页面不进入普通求职导航。种子数据仅用于验证评测链路，不能作为人工金标质量结论。</p></header>
    {error && <p className="rounded-xl border border-rose-200 bg-rose-50 p-4 text-sm text-rose-800">{error}</p>}
    <section className="grid gap-5 lg:grid-cols-[1fr_1.2fr]">
      <article className="panel space-y-4"><div className="flex items-center justify-between"><div><p className="eyebrow">新建运行</p><h2 className="mt-1 text-xl font-semibold">固定版本与配置</h2></div><button className="rounded-lg border border-indigo-200 px-3 py-2 text-sm text-indigo-700" disabled={busy} onClick={() => void importSeed()} type="button">导入待标注种子集</button></div>
        <label className="block text-sm text-slate-700">数据集<select className="mt-1 w-full rounded-xl border border-slate-200 px-3 py-2.5" onChange={(event) => setDatasetId(event.target.value)} value={datasetId}><option value="">请选择</option>{datasets.map((item) => <option key={item.id} value={item.id}>{item.name} · {item.version} · {item.case_count} cases</option>)}</select></label>
        <div className="grid gap-3 sm:grid-cols-2"><label className="text-sm text-slate-700">模型<input className="mt-1 w-full rounded-xl border border-slate-200 px-3 py-2.5" onChange={(event) => setModel(event.target.value)} value={model} /></label><label className="text-sm text-slate-700">Prompt 版本<input className="mt-1 w-full rounded-xl border border-slate-200 px-3 py-2.5" onChange={(event) => setPromptVersion(event.target.value)} value={promptVersion} /></label></div>
        <label className="block text-sm text-slate-700">Final Top-K<input className="mt-1 w-full" max={50} min={1} onChange={(event) => setFinalTopK(Number(event.target.value))} type="range" value={finalTopK} /><span className="text-xs text-slate-500">{finalTopK}</span></label>
        <details className="rounded-xl border border-slate-200 p-3">
          <summary className="cursor-pointer text-sm font-medium text-slate-700">RAG 实验参数</summary>
          <div className="mt-3 grid gap-3 sm:grid-cols-2">
            <label className="text-xs text-slate-600">Chunk Size<input className="mt-1 w-full rounded-lg border border-slate-200 px-2 py-2" min={64} max={2048} onChange={(event) => setChunkSize(Number(event.target.value))} type="number" value={chunkSize} /></label>
            <label className="text-xs text-slate-600">Chunk Overlap<input className="mt-1 w-full rounded-lg border border-slate-200 px-2 py-2" min={0} max={512} onChange={(event) => setChunkOverlap(Number(event.target.value))} type="number" value={chunkOverlap} /></label>
            <label className="text-xs text-slate-600">Dense Top-K<input className="mt-1 w-full rounded-lg border border-slate-200 px-2 py-2" min={1} max={100} onChange={(event) => setDenseTopK(Number(event.target.value))} type="number" value={denseTopK} /></label>
            <label className="text-xs text-slate-600">Sparse Top-K<input className="mt-1 w-full rounded-lg border border-slate-200 px-2 py-2" min={1} max={100} onChange={(event) => setSparseTopK(Number(event.target.value))} type="number" value={sparseTopK} /></label>
            <label className="text-xs text-slate-600">RRF k<input className="mt-1 w-full rounded-lg border border-slate-200 px-2 py-2" min={1} max={200} onChange={(event) => setRrfK(Number(event.target.value))} type="number" value={rrfK} /></label>
            <label className="text-xs text-slate-600">Dense 权重（Sparse 自动互补）<input className="mt-1 w-full rounded-lg border border-slate-200 px-2 py-2" min={0} max={1} step={0.05} onChange={(event) => setDenseWeight(Number(event.target.value))} type="number" value={denseWeight} /></label>
            <label className="text-xs text-slate-600">最低相关度<input className="mt-1 w-full rounded-lg border border-slate-200 px-2 py-2" min={0} max={1} step={0.01} onChange={(event) => setMinimumRelevance(Number(event.target.value))} type="number" value={minimumRelevance} /></label>
            <div className="space-y-2 pt-1 text-xs text-slate-600"><label className="flex items-center gap-2"><input checked={rerankerEnabled} onChange={(event) => setRerankerEnabled(event.target.checked)} type="checkbox" />Reranker</label><label className="flex items-center gap-2"><input checked={queryRewrite} onChange={(event) => setQueryRewrite(event.target.checked)} type="checkbox" />Query Rewrite</label><label className="flex items-center gap-2"><input checked={metadataFilter} onChange={(event) => setMetadataFilter(event.target.checked)} type="checkbox" />Metadata Filter</label></div>
          </div>
          <p className="mt-3 text-xs leading-5 text-amber-700">Chunk Size / Overlap 只有在使用对应独立索引快照采集 observations 时才构成有效消融，控制台不会把同一批检索结果伪装成不同切块实验。</p>
        </details>
        <label className="block text-sm text-slate-700">Observations JSON<textarea className="mt-1 min-h-36 w-full rounded-xl border border-slate-200 p-3 font-mono text-xs" onChange={(event) => setObservations(event.target.value)} spellCheck={false} value={observations} /></label>
        <label className="flex items-center gap-2 text-sm text-slate-600"><input checked={requireGold} onChange={(event) => setRequireGold(event.target.checked)} type="checkbox" />只允许已完成双人标注与仲裁的数据</label>
        <button className="w-full rounded-xl bg-indigo-600 px-4 py-3 font-medium text-white disabled:opacity-50" disabled={busy || !datasetId} onClick={() => void start()} type="button">{busy ? "处理中…" : "后台启动评测"}</button>
      </article>
      <article className="panel"><p className="eyebrow">运行结果</p>{!active ? <p className="mt-6 text-sm text-slate-500">尚无评测记录</p> : <div className="mt-4 space-y-4"><div className="flex flex-wrap items-center justify-between gap-3"><div><p className="font-mono text-xs text-slate-500">{active.id}</p><p className="mt-1 font-semibold">{active.status}</p>{isNonGoldRun(active, datasets) && <p className="mt-1 text-xs font-medium text-amber-700">非金标链路测试，不代表模型质量</p>}</div><div className="flex gap-2">{!terminal.has(active.status) && <button className="rounded-lg border border-rose-200 px-3 py-2 text-sm text-rose-700" onClick={() => void action(active, "cancel")} type="button">取消</button>}{["FAILED", "CANCELLED"].includes(active.status) && <button className="rounded-lg border border-indigo-200 px-3 py-2 text-sm text-indigo-700" onClick={() => void action(active, "retry")} type="button">重试</button>}</div></div><div><div className="h-2 overflow-hidden rounded-full bg-slate-100"><div className="h-full bg-indigo-600 transition-all duration-500" style={{ width: `${active.progress_total ? active.progress_current / active.progress_total * 100 : 0}%` }} /></div><p className="mt-1 text-xs text-slate-500">{active.progress_current} / {active.progress_total}</p></div>{active.error && <p className="rounded-lg bg-rose-50 p-3 text-sm text-rose-800">{active.error}</p>}<div className="grid gap-2 sm:grid-cols-2">{Object.entries(summary(active)).map(([key, value]) => <div className="rounded-xl border border-slate-200 bg-slate-50 p-3" key={key}><p className="text-xs text-slate-500">{key}</p><p className="mt-1 font-semibold">{typeof value === "number" ? value.toFixed(4) : String(value)}</p></div>)}</div>{failedCases(active).length > 0 && <details className="rounded-xl border border-amber-200 bg-amber-50 p-3"><summary className="cursor-pointer text-sm font-semibold text-amber-800">失败案例 · {failedCases(active).length}</summary><div className="mt-3 max-h-64 space-y-2 overflow-y-auto">{failedCases(active).slice(0, 20).map((item, index) => <div className="rounded-lg border border-amber-100 bg-white/70 p-2" key={String(item.case_id ?? index)}><p className="font-mono text-xs font-medium text-slate-700">{String(item.case_id ?? `case-${index + 1}`)}</p><pre className="mt-1 whitespace-pre-wrap break-words text-[11px] leading-4 text-slate-500">{JSON.stringify(item, null, 2)}</pre></div>)}</div></details>}{active.status === "SUCCEEDED" && <div className="flex gap-2"><button className="text-sm text-indigo-700" onClick={() => download(active, "json")} type="button">导出 JSON</button><button className="text-sm text-indigo-700" onClick={() => download(active, "csv")} type="button">CSV</button><button className="text-sm text-indigo-700" onClick={() => download(active, "md")} type="button">Markdown</button></div>}</div>}</article>
    </section>
    <section className="panel"><div className="flex flex-wrap items-end justify-between gap-3"><div><p className="eyebrow">历史与对比</p><h2 className="mt-1 text-xl font-semibold">最近 100 次运行</h2></div><div className="flex flex-wrap gap-2"><select className="rounded-lg border border-slate-200 px-2 py-2 text-sm" onChange={(event) => setLeftId(event.target.value)} value={leftId}><option value="">基线</option>{runs.filter((run) => run.status === "SUCCEEDED").map((run) => <option key={run.id} value={run.id}>{run.id.slice(0, 8)}</option>)}</select><select className="rounded-lg border border-slate-200 px-2 py-2 text-sm" onChange={(event) => setRightId(event.target.value)} value={rightId}><option value="">候选</option>{runs.filter((run) => run.status === "SUCCEEDED").map((run) => <option key={run.id} value={run.id}>{run.id.slice(0, 8)}</option>)}</select><button className="rounded-lg bg-slate-900 px-3 py-2 text-sm text-white disabled:opacity-50" disabled={!leftId || !rightId} onClick={() => void compareEvaluationRuns(leftId, rightId).then((value) => setDelta(value.metric_delta)).catch((reason) => setError(reason instanceof Error ? reason.message : "对比失败"))} type="button">对比</button></div></div>{Object.keys(delta).length > 0 && <div className="mt-4 flex flex-wrap gap-2">{Object.entries(delta).map(([key, value]) => <span className={`rounded-full px-3 py-1 text-xs ${value >= 0 ? "bg-emerald-50 text-emerald-700" : "bg-rose-50 text-rose-700"}`} key={key}>{key} {value >= 0 ? "+" : ""}{value.toFixed(4)}</span>)}</div>}<div className="mt-4 overflow-x-auto"><table className="w-full text-left text-sm"><thead className="bg-slate-50 text-xs text-slate-500"><tr><th className="px-3 py-2">运行</th><th className="px-3 py-2">状态</th><th className="px-3 py-2">进度</th><th className="px-3 py-2">时间</th></tr></thead><tbody>{runs.map((run) => <tr className="cursor-pointer border-t border-slate-100 hover:bg-slate-50" key={run.id} onClick={() => setSelectedRun(run.id)}><td className="px-3 py-3 font-mono text-xs">{run.id.slice(0, 12)}</td><td className="px-3 py-3">{run.status}</td><td className="px-3 py-3">{run.progress_current}/{run.progress_total}</td><td className="px-3 py-3 text-slate-500">{new Date(run.created_at).toLocaleString()}</td></tr>)}</tbody></table></div></section>
  </div>;
}
