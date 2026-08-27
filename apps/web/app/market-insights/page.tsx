"use client";

import Link from "next/link";
import { useEffect, useMemo, useState } from "react";

import {
  createMarketInsight,
  deleteMarketInsight,
  getMarketInsight,
  getMarketInsights,
  marketInsightAction,
  type InsightDistribution,
  type InsightSkill,
  type MarketInsight,
  type MarketInsightMode,
} from "../../lib/api";

const statusLabels: Record<string, string> = {
  PENDING: "排队中",
  RUNNING: "分析中",
  SUCCEEDED: "已完成",
  FAILED: "失败",
  CANCELLED: "已取消",
};

const stageLabels: Record<string, string> = {
  queued: "等待执行",
  searching_jobs: "召回相关岗位",
  aggregating: "聚合薪资、要求和技能",
  llm_summary: "生成深度总结",
  saving: "保存报告",
  completed: "分析完成",
  failed: "生成失败",
  cancelled: "已取消",
};

const confidenceLabels: Record<string, string> = {
  high: "高",
  medium: "中",
  insufficient: "样本不足",
};

function Distribution({ items }: { items: InsightDistribution[] }) {
  if (!items.length) return <p className="text-sm text-slate-500">暂无可识别数据</p>;
  return (
    <div className="space-y-3">
      {items.map((item) => (
        <div key={item.label}>
          <div className="mb-1 flex justify-between text-sm">
            <span className="font-medium text-slate-700">{item.label}</span>
            <span className="text-slate-500">{item.count} 条 · {item.percentage}%</span>
          </div>
          <div className="h-2 overflow-hidden rounded-full bg-slate-100">
            <div className="h-full rounded-full bg-indigo-500" style={{ width: `${item.percentage}%` }} />
          </div>
        </div>
      ))}
    </div>
  );
}

function MarkdownSummary({ value }: { value: string }) {
  return (
    <div className="space-y-2 text-sm leading-7 text-slate-700">
      {value.split("\n").filter(Boolean).map((line, index) => {
        if (line.startsWith("# ")) return <h2 className="text-xl font-semibold text-slate-900" key={index}>{line.slice(2)}</h2>;
        if (line.startsWith("- ")) return <p className="pl-3" key={index}>• {line.slice(2).replaceAll("**", "")}</p>;
        return <p key={index}>{line.replaceAll("**", "")}</p>;
      })}
    </div>
  );
}

export default function MarketInsightsPage() {
  const [items, setItems] = useState<MarketInsight[]>([]);
  const [selected, setSelected] = useState<MarketInsight | null>(null);
  const [query, setQuery] = useState("");
  const [cities, setCities] = useState("");
  const [jobTypes, setJobTypes] = useState("");
  const [mode, setMode] = useState<MarketInsightMode>("fast");
  const [maxJobs, setMaxJobs] = useState(50);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function reload(preferredId?: string) {
    const response = await getMarketInsights();
    setItems(response.items);
    const id = preferredId ?? selected?.id;
    setSelected(response.items.find((item) => item.id === id) ?? response.items[0] ?? null);
  }

  useEffect(() => {
    getMarketInsights()
      .then((response) => {
        setItems(response.items);
        setSelected(response.items[0] ?? null);
      })
      .catch((reason) => setError(reason instanceof Error ? reason.message : "无法加载职业洞察"));
  }, []);

  const pollingId = selected && ["PENDING", "RUNNING"].includes(selected.status) ? selected.id : null;
  useEffect(() => {
    if (!pollingId) return;
    const timer = window.setInterval(() => {
      getMarketInsight(pollingId)
        .then((next) => {
          setSelected(next);
          setItems((current) => current.map((item) => item.id === next.id ? next : item));
          if (!["PENDING", "RUNNING"].includes(next.status)) window.clearInterval(timer);
        })
        .catch((reason) => setError(reason instanceof Error ? reason.message : "读取进度失败"));
    }, 1000);
    return () => window.clearInterval(timer);
  }, [pollingId]);

  async function handleCreate() {
    if (!query.trim()) {
      setError("请输入岗位方向或岗位需求。");
      return;
    }
    setSubmitting(true);
    setError(null);
    try {
      const report = await createMarketInsight({
        query: query.trim(),
        mode,
        cities: cities.split(/[，,]/).map((item) => item.trim()).filter(Boolean),
        job_types: jobTypes.split(/[，,]/).map((item) => item.trim()).filter(Boolean),
        max_jobs: maxJobs,
      });
      setSelected(report);
      await reload(report.id);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "创建分析失败");
    } finally {
      setSubmitting(false);
    }
  }

  async function handleAction(action: "cancel" | "retry") {
    if (!selected) return;
    setError(null);
    try {
      const report = await marketInsightAction(selected.id, action);
      setSelected(report);
      await reload(report.id);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "操作失败");
    }
  }

  async function handleDelete() {
    if (!selected || !window.confirm(`删除“${selected.query}”报告？`)) return;
    try {
      await deleteMarketInsight(selected.id);
      setSelected(null);
      await reload();
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "删除失败");
    }
  }

  const report = selected?.report;
  const skillGroups = useMemo(() => {
    const groups: Record<string, InsightSkill[]> = { core: [], high_frequency: [], bonus: [], emerging: [] };
    report?.skills.forEach((skill) => groups[skill.category].push(skill));
    return groups;
  }, [report]);

  function downloadMarkdown() {
    if (!report) return;
    const evidence = report.source_jobs.map((job) => `- [${job.title}](${job.source_url || `/jobs/${job.id}`}) · ${job.company || "公司未注明"}`).join("\n");
    const content = `${report.summary_markdown}\n\n## 学习路线\n\n${report.learning_roadmap.map((phase) => `### ${phase.weeks} ${phase.title}\n\n- 目标：${phase.objectives.join("；")}\n- 技能：${phase.skills.join("、")}\n- 交付物：${phase.deliverables.join("；")}`).join("\n\n")}\n\n## 样本岗位\n\n${evidence}`;
    const url = URL.createObjectURL(new Blob([content], { type: "text/markdown;charset=utf-8" }));
    const link = document.createElement("a");
    link.href = url;
    link.download = `${report.query}-职业洞察.md`;
    link.click();
    URL.revokeObjectURL(url);
  }

  return (
    <div className="mx-auto max-w-7xl space-y-6">
      <header>
        <p className="eyebrow">Job market agent</p>
        <h1 className="mt-2 text-3xl font-semibold text-slate-900">职业洞察</h1>
        <p className="mt-2 max-w-3xl text-sm leading-6 text-slate-500">综合系统内真实 JD，分析薪资、学历、经验、技能和典型职责，并生成可执行的 12 周学习路线。</p>
      </header>

      {error && <div className="rounded-xl border border-rose-200 bg-rose-50 px-4 py-3 text-sm text-rose-700">{error}</div>}

      <section className="panel space-y-5">
        <div>
          <label className="mb-2 block text-sm font-semibold text-slate-800" htmlFor="insight-query">你想了解什么岗位方向？</label>
          <textarea id="insight-query" className="min-h-24 w-full rounded-xl border border-slate-200 px-4 py-3 outline-none transition focus:border-indigo-400 focus:ring-2 focus:ring-indigo-100" onChange={(event) => setQuery(event.target.value)} placeholder="例如：机器人控制算法实习生；AI Agent / RAG 工程师；我想做具身智能，需要学习什么？" value={query} />
        </div>
        <div className="grid gap-4 md:grid-cols-4">
          <label className="text-sm text-slate-600">城市（可选）<input className="mt-2 w-full rounded-xl border border-slate-200 px-3 py-2.5" onChange={(event) => setCities(event.target.value)} placeholder="北京, 上海" value={cities} /></label>
          <label className="text-sm text-slate-600">工作类型（可选）<input className="mt-2 w-full rounded-xl border border-slate-200 px-3 py-2.5" onChange={(event) => setJobTypes(event.target.value)} placeholder="实习, 全职" value={jobTypes} /></label>
          <label className="text-sm text-slate-600">最大样本数<select className="mt-2 w-full rounded-xl border border-slate-200 px-3 py-2.5" onChange={(event) => setMaxJobs(Number(event.target.value))} value={maxJobs}><option value={20}>20</option><option value={50}>50</option><option value={100}>100</option></select></label>
          <div className="text-sm text-slate-600">分析模式<div className="mt-2 flex rounded-xl border border-slate-200 p-1"><button className={`flex-1 rounded-lg px-2 py-2 ${mode === "fast" ? "bg-indigo-600 text-white" : "text-slate-600"}`} onClick={() => setMode("fast")}>快速</button><button className={`flex-1 rounded-lg px-2 py-2 ${mode === "llm" ? "bg-indigo-600 text-white" : "text-slate-600"}`} onClick={() => setMode("llm")}>LLM 深度</button></div></div>
        </div>
        <div className="flex flex-wrap items-center justify-between gap-3">
          <p className="text-xs text-slate-500">快速模式只做确定性统计；深度模式仅使用 LLM 优化总结和路线，不改写统计数字。</p>
          <button className="rounded-xl bg-indigo-600 px-5 py-3 text-sm font-semibold text-white shadow-sm disabled:opacity-50" disabled={submitting} onClick={handleCreate}>{submitting ? "正在创建…" : "生成职业洞察"}</button>
        </div>
      </section>

      <div className="grid gap-6 lg:grid-cols-[280px_minmax(0,1fr)]">
        <aside className="panel h-fit p-4">
          <div className="mb-3 flex items-center justify-between"><h2 className="font-semibold text-slate-900">历史报告</h2><span className="text-xs text-slate-400">{items.length}</span></div>
          <div className="space-y-2">
            {items.map((item) => <button className={`w-full rounded-xl border p-3 text-left transition ${selected?.id === item.id ? "border-indigo-300 bg-indigo-50" : "border-slate-100 hover:bg-slate-50"}`} key={item.id} onClick={() => setSelected(item)}><span className="block truncate text-sm font-medium text-slate-800">{item.query}</span><span className="mt-1 flex justify-between text-xs text-slate-500"><span>{statusLabels[item.status] ?? item.status}</span><span>{new Date(item.created_at).toLocaleDateString("zh-CN")}</span></span></button>)}
            {!items.length && <p className="py-8 text-center text-sm text-slate-400">暂无报告</p>}
          </div>
        </aside>

        <main className="min-w-0 space-y-6">
          {!selected && <section className="panel py-16 text-center text-slate-500">输入岗位方向，生成第一份职业洞察。</section>}
          {selected && ["PENDING", "RUNNING"].includes(selected.status) && <section className="panel"><div className="flex items-center justify-between"><div><p className="eyebrow">正在分析</p><h2 className="mt-1 text-xl font-semibold">{selected.query}</h2></div><button className="rounded-lg border border-rose-200 px-3 py-2 text-sm text-rose-600" onClick={() => handleAction("cancel")}>取消</button></div><p className="mt-5 text-sm text-slate-500">{stageLabels[selected.stage] ?? selected.stage}</p><div className="mt-2 h-3 overflow-hidden rounded-full bg-slate-100"><div className="h-full rounded-full bg-indigo-500 transition-all" style={{ width: `${selected.progress}%` }} /></div><p className="mt-2 text-right text-xs text-slate-400">{selected.progress}% · 已召回 {selected.sample_count} 条</p></section>}
          {selected && ["FAILED", "CANCELLED"].includes(selected.status) && <section className="panel"><h2 className="text-lg font-semibold">{statusLabels[selected.status]}</h2><p className="mt-2 text-sm text-rose-600">{selected.error}</p><div className="mt-4 flex gap-2"><button className="rounded-lg bg-indigo-600 px-4 py-2 text-sm text-white" onClick={() => handleAction("retry")}>重试</button><button className="rounded-lg border border-slate-200 px-4 py-2 text-sm" onClick={handleDelete}>删除</button></div></section>}

          {selected?.status === "SUCCEEDED" && report && <>
            <section className="panel">
              <div className="flex flex-wrap items-start justify-between gap-4"><div><p className="eyebrow">分析完成</p><h2 className="mt-1 text-2xl font-semibold text-slate-900">{report.query}</h2><p className="mt-2 text-xs text-slate-400">{report.sample_count} 条样本 · 置信度 {confidenceLabels[report.confidence] ?? report.confidence} · {report.llm_source}</p></div><div className="flex gap-2"><button className="rounded-lg border border-indigo-200 px-3 py-2 text-sm text-indigo-700" onClick={downloadMarkdown}>导出 Markdown</button><button className="rounded-lg border border-slate-200 px-3 py-2 text-sm text-slate-600" onClick={handleDelete}>删除</button></div></div>
              {report.warnings.map((warning) => <p className="mt-4 rounded-lg bg-amber-50 px-3 py-2 text-sm text-amber-700" key={warning}>{warning}</p>)}
              <div className="mt-5"><MarkdownSummary value={report.summary_markdown} /></div>
            </section>

            <div className="grid gap-6 md:grid-cols-2">
              <section className="panel"><h3 className="font-semibold text-slate-900">综合薪资</h3><div className="mt-4 space-y-3">{report.salary_bands.map((band) => <div className="rounded-xl bg-slate-50 p-4" key={band.unit}><p className="text-xs text-slate-500">{band.sample_count} 条有效样本 · {band.unit_label}</p><p className="mt-1 text-2xl font-semibold text-indigo-700">{band.median}{band.unit_label}</p><p className="mt-1 text-sm text-slate-500">P25–P75：{band.p25}–{band.p75} · 全区间 {band.minimum}–{band.maximum}</p></div>)}{!report.salary_bands.length && <p className="text-sm text-slate-500">暂无可比较薪资</p>}</div></section>
              <section className="panel"><h3 className="font-semibold text-slate-900">学历要求</h3><div className="mt-4"><Distribution items={report.education_distribution} /></div></section>
              <section className="panel"><h3 className="font-semibold text-slate-900">经验要求</h3><div className="mt-4"><Distribution items={report.experience_distribution} /></div></section>
              <section className="panel"><h3 className="font-semibold text-slate-900">岗位族群</h3><div className="mt-4 space-y-3">{report.role_clusters.map((cluster) => <div key={cluster.name}><div className="flex justify-between text-sm"><span className="font-medium">{cluster.name}</span><span className="text-slate-500">{cluster.count} · {cluster.percentage}%</span></div><p className="mt-1 truncate text-xs text-slate-400">{cluster.titles.join(" / ")}</p></div>)}</div></section>
            </div>

            <section className="panel"><h3 className="font-semibold text-slate-900">技能要求</h3><div className="mt-5 grid gap-5 md:grid-cols-2">{([["core", "核心必备"], ["high_frequency", "高频技能"], ["bonus", "加分项"], ["emerging", "补充技能"]] as const).map(([key, label]) => <div key={key}><p className="mb-2 text-xs font-semibold uppercase tracking-wider text-slate-400">{label}</p><div className="flex flex-wrap gap-2">{skillGroups[key].slice(0, 12).map((skill) => <span className="rounded-full bg-indigo-50 px-3 py-1.5 text-sm text-indigo-700" key={skill.name}>{skill.name} <small>{skill.percentage}%</small></span>)}{!skillGroups[key].length && <span className="text-sm text-slate-400">暂无</span>}</div></div>)}</div></section>

            <section className="panel"><h3 className="font-semibold text-slate-900">典型岗位职责</h3><div className="mt-4 grid gap-4 md:grid-cols-2">{report.responsibility_themes.map((theme) => <div className="rounded-xl border border-slate-100 p-4" key={theme.name}><div className="flex justify-between"><span className="font-medium">{theme.name}</span><span className="text-sm text-indigo-600">{theme.percentage}%</span></div>{theme.examples.slice(0, 2).map((example) => <p className="mt-2 text-sm leading-6 text-slate-500" key={example}>• {example}</p>)}</div>)}</div></section>

            <section className="panel"><h3 className="font-semibold text-slate-900">12 周学习路线</h3><div className="mt-5 space-y-5">{report.learning_roadmap.map((phase, index) => <div className="grid gap-3 border-l-2 border-indigo-200 pl-5 sm:grid-cols-[130px_1fr]" key={phase.weeks}><div><span className="text-xs font-semibold text-indigo-600">{phase.weeks}</span><p className="mt-1 font-semibold">{phase.title}</p></div><div className="text-sm leading-6 text-slate-600"><p>{phase.objectives.join("；")}</p><p className="mt-1"><b>重点：</b>{phase.skills.join("、")}</p><p><b>交付：</b>{phase.deliverables.join("；")}</p><p><b>验收：</b>{phase.success_criteria.join("；")}</p></div></div>)}</div></section>

            <section className="panel"><div className="flex items-center justify-between"><h3 className="font-semibold text-slate-900">证据岗位</h3><span className="text-xs text-slate-400">结论可追溯至 {report.source_jobs.length} 条 JD</span></div><div className="mt-4 divide-y divide-slate-100">{report.source_jobs.map((job) => <div className="flex flex-wrap items-center justify-between gap-3 py-3" key={job.id}><div><Link className="font-medium text-indigo-700 hover:underline" href={`/jobs/${job.id}`}>{job.title}</Link><p className="mt-1 text-xs text-slate-500">{job.company || "公司未注明"} · {job.location || "地点未注明"} · {job.education || "学历未注明"}</p></div><div className="text-right"><p className="text-sm font-medium text-slate-700">{job.salary_text || "薪资未注明"}</p>{job.source_url && <a className="text-xs text-indigo-600 hover:underline" href={job.source_url} rel="noreferrer" target="_blank">查看原职位</a>}</div></div>)}</div></section>
          </>}
        </main>
      </div>
    </div>
  );
}
