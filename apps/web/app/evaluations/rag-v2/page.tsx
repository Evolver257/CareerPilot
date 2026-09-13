"use client";

import { useCallback, useEffect, useMemo, useState } from "react";

import {
  API_BASE_URL,
  getRagV2Queries,
  getRagV2Query,
  getRagV2Status,
  saveRagV2Annotation,
  type RagV2Annotation,
  type RagV2Query,
  type RagV2QueryDetail,
  type RagV2Status,
} from "../../../lib/api";

const gradeOptions: Array<{ value: -1 | 0 | 1 | 2 | 3; label: string; detail: string }> = [
  { value: 3, label: "3 · 核心相关", detail: "岗位方向和主要职责直接满足问题" },
  { value: 2, label: "2 · 明显相关", detail: "大部分需求匹配，但有部分条件缺口" },
  { value: 1, label: "1 · 弱相关", detail: "只满足部分技能或正文偶然提及" },
  { value: 0, label: "0 · 不相关", detail: "岗位与问题不相关" },
  { value: -1, label: "-1 · 信息不足", detail: "现有 JD 信息无法判断" },
];

function emptyAnnotation(detail: RagV2QueryDetail, jobId: string, annotatorId: string): RagV2Annotation {
  return {
    dataset_version: detail.query.split ? "rag-v2.0.0" : "rag-v2.0.0",
    query_id: detail.query.query_id,
    job_id: jobId,
    annotator_id: annotatorId,
    relevance_grade: -1,
    hard_constraint_violation: "uncertain",
    answerability_judgment: detail.query.answerability,
    matched_requirements: [],
    missing_requirements: [],
    evidence_spans: [],
    confidence: "medium",
    annotation_note: "",
    status: "draft",
  };
}

export default function RagV2AnnotationPage() {
  const [annotatorId, setAnnotatorId] = useState("annotator_a");
  const [queries, setQueries] = useState<RagV2Query[]>([]);
  const [status, setStatus] = useState<RagV2Status | null>(null);
  const [queryIndex, setQueryIndex] = useState(0);
  const [jobIndex, setJobIndex] = useState(0);
  const [detail, setDetail] = useState<RagV2QueryDetail | null>(null);
  const [draft, setDraft] = useState<RagV2Annotation | null>(null);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState("");
  const [error, setError] = useState<string | null>(null);

  const activeQuery = queries[queryIndex];
  const activeItem = detail?.items[jobIndex];

  const load = useCallback(async () => {
    setError(null);
    try {
      const [nextStatus, nextQueries] = await Promise.all([getRagV2Status(), getRagV2Queries(annotatorId)]);
      setStatus(nextStatus);
      setQueries(nextQueries);
      setQueryIndex((current) => Math.min(current, Math.max(nextQueries.length - 1, 0)));
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "V2 数据加载失败，请确认后端已启动");
    }
  }, [annotatorId]);

  useEffect(() => { void load(); }, [load]);

  useEffect(() => {
    if (!activeQuery) return;
    setBusy(true);
    void getRagV2Query(activeQuery.query_id, annotatorId)
      .then((next) => {
        setDetail(next);
        setJobIndex(0);
        setDraft(next.items[0] ? next.items[0].annotation ?? emptyAnnotation(next, next.items[0].job.job_id, annotatorId) : null);
      })
      .catch((reason) => setError(reason instanceof Error ? reason.message : "候选岗位加载失败"))
      .finally(() => setBusy(false));
  }, [activeQuery, annotatorId]);

  useEffect(() => {
    if (!detail || !detail.items[jobIndex]) return;
    const item = detail.items[jobIndex];
    setDraft(item.annotation ?? emptyAnnotation(detail, item.job.job_id, annotatorId));
  }, [detail, jobIndex, annotatorId]);

  const selectedGrade = useMemo(() => gradeOptions.find((option) => option.value === draft?.relevance_grade), [draft]);

  const moveJob = useCallback((delta: number) => {
    if (!detail?.items.length) return;
    setJobIndex((current) => Math.max(0, Math.min(detail.items.length - 1, current + delta)));
  }, [detail]);

  const save = useCallback(async (nextStatus: "draft" | "submitted" | "skipped", advance: boolean) => {
    if (!draft) return;
    setBusy(true); setError(null); setMessage("");
    try {
      await saveRagV2Annotation({ ...draft, status: nextStatus });
      setMessage(nextStatus === "submitted" ? "已提交独立标注" : nextStatus === "skipped" ? "已跳过，可稍后恢复" : "已暂存");
      if (advance) moveJob(1);
      await load();
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "标注保存失败");
    } finally { setBusy(false); }
  }, [draft, load, moveJob]);

  useEffect(() => {
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.target instanceof HTMLInputElement || event.target instanceof HTMLTextAreaElement) {
        if (!(event.metaKey || event.ctrlKey) || event.key !== "Enter") return;
      }
      if (event.key === "ArrowLeft") { event.preventDefault(); moveJob(-1); }
      if (event.key === "ArrowRight") { event.preventDefault(); moveJob(1); }
      if (["0", "1", "2", "3"].includes(event.key) && !(event.ctrlKey || event.metaKey)) {
        event.preventDefault();
        setDraft((current) => current ? { ...current, relevance_grade: Number(event.key) as 0 | 1 | 2 | 3 } : current);
      }
      if (event.key === "-" && !(event.ctrlKey || event.metaKey)) {
        event.preventDefault(); setDraft((current) => current ? { ...current, relevance_grade: -1 } : current);
      }
      if ((event.ctrlKey || event.metaKey) && event.key === "Enter") { event.preventDefault(); void save("submitted", true); }
    };
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [moveJob, save]);

  function setField<K extends keyof RagV2Annotation>(key: K, value: RagV2Annotation[K]) {
    setDraft((current) => current ? { ...current, [key]: value } : current);
  }

  const evidenceText = draft?.evidence_spans.map((span) => span.text).join("\n") ?? "";
  const progress = status?.progress[annotatorId];

  return <main className="mx-auto max-w-[1500px] space-y-4 px-4 py-6 text-slate-900 dark:text-slate-100">
    <header className="flex flex-wrap items-end justify-between gap-4">
      <div><p className="eyebrow">开发 / 评测</p><h1 className="mt-2 text-3xl font-semibold">CareerPilot RAG V2 双人标注</h1><p className="mt-2 text-sm text-slate-500 dark:text-slate-400">只显示问题、岗位和 JD 证据；模型分数对标注者隐藏。所有自动标签都只是 silver/prelabel。</p></div>
      <div className="flex flex-wrap items-center justify-end gap-3 text-sm"><div className="flex gap-2 text-xs"><a className="text-indigo-700 hover:underline dark:text-indigo-300" href={`${API_BASE_URL}/api/evaluation-v2/export/annotations.jsonl`} rel="noreferrer" target="_blank">导出标注 JSONL</a><a className="text-indigo-700 hover:underline dark:text-indigo-300" href={`${API_BASE_URL}/api/evaluation-v2/export/adjudications.jsonl`} rel="noreferrer" target="_blank">导出裁决 JSONL</a></div><label htmlFor="annotator">标注者 ID</label><input id="annotator" className="w-36 rounded-lg border border-slate-200 bg-white px-3 py-2 dark:border-slate-700 dark:bg-slate-900" onChange={(event) => setAnnotatorId(event.target.value || "annotator_a")} value={annotatorId} /></div>
    </header>
    {error && <p className="rounded-xl border border-rose-200 bg-rose-50 p-3 text-sm text-rose-800">{error}</p>}
    {message && <p className="rounded-xl border border-emerald-200 bg-emerald-50 p-3 text-sm text-emerald-800">{message}</p>}
    <section className="flex flex-wrap items-center justify-between gap-3 rounded-xl border border-slate-200 bg-white p-3 text-sm shadow-sm dark:border-slate-700 dark:bg-slate-900">
      <div>数据集 <span className="font-mono">{status?.dataset_version ?? "rag-v2.0.0"}</span> · 状态 <span className="font-medium text-amber-700">{status?.label_status ?? "awaiting_review"}</span></div>
      <div>问题 {queries.length ? queryIndex + 1 : 0}/{queries.length} · 候选 {detail?.items.length ? jobIndex + 1 : 0}/{detail?.items.length ?? 0} · 已提交 {progress?.submitted ?? 0}/{status?.candidate_pair_count ?? 0}</div>
    </section>
    <section className="grid gap-4 lg:grid-cols-[260px_minmax(0,1fr)_300px]">
      <aside className="panel max-h-[calc(100vh-220px)] overflow-y-auto p-3 dark:bg-slate-900">
        <div className="mb-3 flex items-center justify-between"><h2 className="font-semibold">问题队列</h2><span className="text-xs text-slate-500">{queries.length} 条</span></div>
        <div className="space-y-1">{queries.map((query, index) => <button className={`w-full rounded-lg p-2 text-left text-xs ${index === queryIndex ? "bg-indigo-50 text-indigo-800 dark:bg-indigo-950 dark:text-indigo-200" : "hover:bg-slate-50 dark:hover:bg-slate-800"}`} key={query.query_id} onClick={() => { setQueryIndex(index); setJobIndex(0); }} type="button"><div className="flex justify-between gap-2"><span className="font-mono">{query.query_id.replace("rag-v2-", "")}</span><span>{query.submitted_count ?? 0}/{query.candidate_count ?? 0}</span></div><p className="mt-1 line-clamp-2">{query.query}</p><span className="mt-1 inline-block rounded bg-slate-100 px-1.5 py-0.5 text-[10px] dark:bg-slate-800">{query.query_type} · {query.split}</span></button>)}</div>
      </aside>
      <article className="panel min-h-[calc(100vh-220px)] space-y-4 p-5 dark:bg-slate-900">
        {!activeItem || !detail ? <p className="text-sm text-slate-500">{busy ? "加载中…" : "暂无候选岗位"}</p> : <>
          <div className="rounded-xl bg-slate-50 p-4 dark:bg-slate-800"><p className="text-xs text-slate-500">求职问题 · {detail.query.query_type}</p><h2 className="mt-1 text-xl font-semibold">{detail.query.query}</h2><p className="mt-2 text-sm text-slate-500">意图：{detail.query.normalized_intent} · 答案可得性：{detail.query.answerability}</p><div className="mt-3 flex flex-wrap gap-2">{detail.query.target_role.map((item) => <span className="rounded-full bg-indigo-100 px-2 py-1 text-xs text-indigo-800 dark:bg-indigo-950 dark:text-indigo-200" key={item}>岗位：{item}</span>)}{detail.query.target_skills.map((item) => <span className="rounded-full bg-violet-100 px-2 py-1 text-xs text-violet-800 dark:bg-violet-950 dark:text-violet-200" key={item}>技能：{item}</span>)}</div><dl className="mt-3 grid gap-2 text-xs sm:grid-cols-2"><div><dt className="text-slate-500">硬约束</dt><dd>{Object.keys(detail.query.hard_constraints).length ? JSON.stringify(detail.query.hard_constraints) : "无"}</dd></div><div><dt className="text-slate-500">软偏好</dt><dd>{Object.keys(detail.query.soft_preferences).length ? JSON.stringify(detail.query.soft_preferences) : "无"}</dd></div></dl></div>
          <div className="flex items-start justify-between gap-3 border-b border-slate-200 pb-3 dark:border-slate-700"><div><p className="text-xs text-slate-500">候选 #{activeItem.candidate_rank} · {activeItem.job.platform}</p><h3 className="mt-1 text-2xl font-semibold">{activeItem.job.title}</h3><p className="mt-1 text-sm text-slate-600 dark:text-slate-300">{activeItem.job.company || "公司未提供"} · {activeItem.job.location || activeItem.job.city} · {activeItem.job.job_type}</p></div><div className="text-right text-xs text-slate-500"><p>{activeItem.job.education_level}</p><p>{activeItem.job.experience_level}</p><p>{activeItem.job.salary_min ?? "—"}-{activeItem.job.salary_max ?? "—"}</p></div></div>
          <div className="max-h-[52vh] overflow-y-auto whitespace-pre-wrap rounded-xl border border-slate-200 p-4 text-sm leading-7 dark:border-slate-700">{activeItem.job.description}</div>
          <div className="flex flex-wrap items-center justify-between gap-2 text-xs text-slate-500"><span>来源通道：{activeItem.channels.join("、") || "未记录"}</span><span>快捷键：0–3 / - 评分 · ← → 切换 · Ctrl/Cmd+Enter 提交并下一条</span></div>
        </>}</article>
      <aside className="panel space-y-4 p-4 dark:bg-slate-900">
        <div><p className="eyebrow">独立判断</p><h2 className="mt-1 text-lg font-semibold">相关性等级</h2></div>
        <div className="space-y-2">{gradeOptions.map((option) => <button className={`w-full rounded-lg border p-2 text-left ${draft?.relevance_grade === option.value ? "border-indigo-500 bg-indigo-50 dark:bg-indigo-950" : "border-slate-200 dark:border-slate-700"}`} key={option.value} onClick={() => setField("relevance_grade", option.value)} type="button"><span className="text-sm font-medium">{option.label}</span><span className="mt-0.5 block text-xs text-slate-500">{option.detail}</span></button>)}</div>
        <label className="block text-sm">硬约束是否违反<select className="mt-1 w-full rounded-lg border border-slate-200 bg-white px-2 py-2 dark:border-slate-700 dark:bg-slate-900" onChange={(event) => setField("hard_constraint_violation", event.target.value as RagV2Annotation["hard_constraint_violation"])} value={draft?.hard_constraint_violation ?? "uncertain"}><option value="no">否</option><option value="yes">是</option><option value="uncertain">不确定</option></select></label>
        <label className="block text-sm">答案可得性判断<select className="mt-1 w-full rounded-lg border border-slate-200 bg-white px-2 py-2 dark:border-slate-700 dark:bg-slate-900" onChange={(event) => setField("answerability_judgment", event.target.value as RagV2Annotation["answerability_judgment"])} value={draft?.answerability_judgment ?? "uncertain"}><option value="answerable">可回答</option><option value="unanswerable">无答案</option><option value="uncertain">不确定</option></select></label>
        <label className="block text-sm">匹配要求（每行一条）<textarea className="mt-1 min-h-16 w-full rounded-lg border border-slate-200 bg-white p-2 text-xs dark:border-slate-700 dark:bg-slate-900" onChange={(event) => setField("matched_requirements", event.target.value.split("\n").filter(Boolean))} value={draft?.matched_requirements.join("\n") ?? ""} /></label>
        <label className="block text-sm">缺失要求（每行一条）<textarea className="mt-1 min-h-16 w-full rounded-lg border border-slate-200 bg-white p-2 text-xs dark:border-slate-700 dark:bg-slate-900" onChange={(event) => setField("missing_requirements", event.target.value.split("\n").filter(Boolean))} value={draft?.missing_requirements.join("\n") ?? ""} /></label>
        <label className="block text-sm">JD 证据原文（每行一段）<textarea className="mt-1 min-h-20 w-full rounded-lg border border-slate-200 bg-white p-2 text-xs dark:border-slate-700 dark:bg-slate-900" onChange={(event) => { const texts = event.target.value.split("\n").filter(Boolean); const description = activeItem?.job.description ?? ""; setField("evidence_spans", texts.map((text) => { const start = Math.max(0, description.indexOf(text)); return { start, end: start + text.length, text }; })); }} value={evidenceText} /></label>
        <label className="block text-sm">置信度<select className="mt-1 w-full rounded-lg border border-slate-200 bg-white px-2 py-2 dark:border-slate-700 dark:bg-slate-900" onChange={(event) => setField("confidence", event.target.value as RagV2Annotation["confidence"])} value={draft?.confidence ?? "medium"}><option value="high">高</option><option value="medium">中</option><option value="low">低</option></select></label>
        <label className="block text-sm">备注<textarea className="mt-1 min-h-20 w-full rounded-lg border border-slate-200 bg-white p-2 text-xs dark:border-slate-700 dark:bg-slate-900" onChange={(event) => setField("annotation_note", event.target.value)} value={draft?.annotation_note ?? ""} /></label>
        <div className="flex gap-2"><button className="flex-1 rounded-lg border border-slate-300 px-3 py-2 text-sm disabled:opacity-50" disabled={busy || !draft} onClick={() => void save("draft", false)} type="button">暂存</button><button className="flex-1 rounded-lg border border-amber-300 px-3 py-2 text-sm text-amber-800 disabled:opacity-50" disabled={busy || !draft} onClick={() => void save("skipped", true)} type="button">跳过</button></div><button className="w-full rounded-lg bg-indigo-600 px-3 py-2.5 text-sm font-medium text-white disabled:opacity-50" disabled={busy || !draft || !selectedGrade} onClick={() => void save("submitted", true)} type="button">提交并下一条</button>
      </aside>
    </section>
  </main>;
}
