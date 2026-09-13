"use client";

import { useEffect, useMemo, useState } from "react";

import {
  batchDeleteAgentMemories,
  cancelAgentMemoryEmbeddingRun,
  clearAgentMemories,
  createAgentMemoryEmbeddingRun,
  deleteAgentMemory,
  downloadAgentMemoryExport,
  getAgentMemories,
  getAgentMemoryEmbeddingRuns,
  getAgentMemoryEmbeddingHealth,
  getAgentMemoryHistory,
  getAgentMemorySettings,
  markAgentMemoryOutdated,
  resolveAgentMemoryMaintenanceAction,
  retryAgentMemoryEmbeddingRun,
  runAgentMemoryMaintenance,
  restoreAgentMemory,
  updateAgentMemory,
  updateAgentMemorySettings,
  type AgentMemory,
  type AgentMemoryExtractionMethod,
  type AgentMemoryEmbeddingRun,
  type AgentMemoryEmbeddingHealth,
  type AgentMemorySettings,
  type AgentMemoryType,
} from "../lib/api";

const memoryTypes: Array<{ value: AgentMemoryType; label: string }> = [
  { value: "CAREER_GOAL", label: "职业目标" },
  { value: "JOB_PREFERENCE", label: "岗位偏好" },
  { value: "SKILL_BACKGROUND", label: "技能背景" },
  { value: "LEARNING_PROGRESS", label: "学习进度" },
  { value: "USER_PROFILE", label: "用户画像" },
  { value: "USER_CONFIRMED_FACT", label: "已确认事实" },
  { value: "CONVERSATION_SUMMARY", label: "会话摘要" },
];

function typeLabel(value: AgentMemoryType) {
  return memoryTypes.find((item) => item.value === value)?.label ?? value;
}

type MaintenanceGroup = {
  memory_ids?: string[];
  items?: Array<{ id: string; memory_type?: string; scope?: string }>;
};

function maintenanceGroups(run: AgentMemoryEmbeddingRun, key: string): MaintenanceGroup[] {
  const value = run.result_payload[key];
  return Array.isArray(value) ? value.filter((item): item is MaintenanceGroup => Boolean(item && typeof item === "object")) : [];
}

function MaintenanceFindings({
  run,
  busy,
  onResolve,
}: {
  run: AgentMemoryEmbeddingRun;
  busy: boolean;
  onResolve: (action: "merge_duplicate" | "supersede_conflict", sourceId: string, targetId: string) => void;
}) {
  const duplicateGroups = maintenanceGroups(run, "duplicate_groups");
  const conflictGroups = maintenanceGroups(run, "conflict_groups");
  if (!duplicateGroups.length && !conflictGroups.length) return null;
  return <div className="mt-3 space-y-2 rounded-lg border border-amber-200 bg-amber-50 p-3 text-xs text-amber-900">
    <p className="font-medium">历史数据治理建议（可选调整）</p>
    {duplicateGroups.map((group, index) => {
      const ids = group.memory_ids ?? [];
      if (ids.length < 2) return null;
      return <div className="flex flex-wrap items-center justify-between gap-2" key={`duplicate-${index}`}><span>第 {index + 1} 组重复记忆（{ids.length} 条）</span><button className="rounded border border-amber-300 bg-white px-2 py-1 text-amber-800" disabled={busy} onClick={() => onResolve("merge_duplicate", ids[1], ids[0])} type="button">保留第 1 条并合并</button></div>;
    })}
    {conflictGroups.map((group, index) => {
      const ids = (group.items ?? []).map((item) => item.id).filter(Boolean);
      if (ids.length < 2) return null;
      return <div className="flex flex-wrap items-center justify-between gap-2" key={`conflict-${index}`}><span>属性 {group.items?.[0]?.memory_type ?? "记忆"} 存在冲突（{ids.length} 条）</span><button className="rounded border border-amber-300 bg-white px-2 py-1 text-amber-800" disabled={busy} onClick={() => onResolve("supersede_conflict", ids[1], ids[0])} type="button">保留第 1 条</button></div>;
    })}
  </div>;
}

export function MemorySettingsPanel() {
  const [settings, setSettings] = useState<AgentMemorySettings | null>(null);
  const [items, setItems] = useState<AgentMemory[]>([]);
  const [embeddingRuns, setEmbeddingRuns] = useState<AgentMemoryEmbeddingRun[]>([]);
  const [embeddingHealth, setEmbeddingHealth] = useState<AgentMemoryEmbeddingHealth | null>(null);
  const [query, setQuery] = useState("");
  const [type, setType] = useState<AgentMemoryType | "">("");
  const [includeDeleted, setIncludeDeleted] = useState(false);
  const [status, setStatus] = useState<AgentMemory["status"] | "">("");
  const [extractionMethod, setExtractionMethod] = useState<AgentMemoryExtractionMethod | "">("");
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [editing, setEditing] = useState<string | null>(null);
  const [historyFor, setHistoryFor] = useState<string | null>(null);
  const [history, setHistory] = useState<AgentMemory[]>([]);
  const [draft, setDraft] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [confirmClear, setConfirmClear] = useState(false);
  const [page, setPage] = useState(0);
  const [total, setTotal] = useState(0);
  const [hasMore, setHasMore] = useState(false);
  const [memoryBudgetDraft, setMemoryBudgetDraft] = useState("");
  const pageSize = 20;

  const activeItems = useMemo(
    () => items.filter((item) => item.status === "ACTIVE" && !item.deleted_at),
    [items],
  );

  async function load(nextPage = page) {
    try {
      const [nextSettings, memories, runs, health] = await Promise.all([
        getAgentMemorySettings(),
        getAgentMemories({
          query,
          memoryType: type,
          includeDeleted,
          status,
          extractionMethod,
          limit: pageSize,
          offset: nextPage * pageSize,
        }),
        getAgentMemoryEmbeddingRuns(),
        getAgentMemoryEmbeddingHealth(),
      ]);
      setSettings(nextSettings);
      setMemoryBudgetDraft(String(nextSettings.memory_token_budget));
      setItems(memories.items);
      setTotal(memories.total);
      setHasMore(memories.has_more);
      setEmbeddingRuns(runs);
      setEmbeddingHealth(health);
      setSelected(new Set());
      setError(null);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "记忆设置加载失败");
    }
  }

  useEffect(() => {
    void load();
    // Query is submitted explicitly to avoid network calls on every keystroke.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [type, includeDeleted, status, extractionMethod, page]);

  useEffect(() => {
    const active = embeddingRuns.some((run) => run.status === "PENDING" || run.status === "RUNNING");
    if (!active) return undefined;
    const timer = window.setInterval(() => {
      void Promise.all([getAgentMemoryEmbeddingRuns(), getAgentMemoryEmbeddingHealth()])
        .then(([runs, health]) => { setEmbeddingRuns(runs); setEmbeddingHealth(health); })
        .catch(() => undefined);
    }, 3000);
    return () => window.clearInterval(timer);
  }, [embeddingRuns]);

  async function run(action: () => Promise<unknown>) {
    setBusy(true);
    setError(null);
    try {
      await action();
      await load();
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "操作失败");
    } finally {
      setBusy(false);
    }
  }

  async function resolveMaintenanceAction(
    action: "merge_duplicate" | "supersede_conflict",
    sourceId: string,
    targetId: string,
  ) {
    const latestRun = embeddingRuns[0];
    if (!latestRun) return;
    await run(() => resolveAgentMemoryMaintenanceAction(latestRun.id, {
      action,
      source_memory_id: sourceId,
      target_memory_id: targetId,
    }));
  }

  if (!settings) {
    return <section className="panel text-sm text-slate-500">正在读取记忆设置…</section>;
  }

  return (
    <section className="panel" aria-labelledby="memory-settings-title">
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div>
          <p className="eyebrow">隐私与个性化</p>
          <h2 className="mt-2 text-xl font-semibold" id="memory-settings-title">职业顾问记忆</h2>
          <p className="mt-2 max-w-2xl text-sm leading-6 text-slate-500">
            开启后，Agent 会依据你的原话自动保存、更新和淘汰职业记忆，无需逐条确认。密钥、联系方式和身份信息不会保存。
          </p>
        </div>
        <button
          aria-pressed={settings.enabled}
          className={`rounded-full px-4 py-2 text-sm font-medium transition ${settings.enabled ? "bg-emerald-100 text-emerald-700" : "bg-slate-100 text-slate-600"}`}
          disabled={busy}
          onClick={() => void run(async () => setSettings(await updateAgentMemorySettings({ enabled: !settings.enabled })))}
          type="button"
        >
          {settings.enabled ? "记忆已开启" : "记忆已暂停"}
        </button>
      </div>

      <div className="mt-5 flex flex-wrap items-end gap-3 rounded-xl border border-slate-200 bg-slate-50 p-4">
        <span className="rounded-lg bg-emerald-100 px-3 py-2 text-sm font-medium text-emerald-700">
          自动维护已启用
        </span>
        <button
          aria-pressed={settings.allow_session_summaries}
          className={`rounded-lg px-3 py-2 text-sm ${settings.allow_session_summaries ? "bg-indigo-100 text-indigo-700" : "bg-white text-slate-600"}`}
          disabled={busy}
          onClick={() => void run(async () => setSettings(await updateAgentMemorySettings({ allow_session_summaries: !settings.allow_session_summaries })))}
          type="button"
        >
          {settings.allow_session_summaries ? "允许会话摘要：开" : "允许会话摘要：关"}
        </button>
        <label className="flex items-center gap-2 text-sm text-slate-700">
          记忆预算
          <input
            aria-label="记忆预算"
            className="w-20 rounded-lg border border-slate-200 px-2 py-2"
            disabled={busy}
            min={200}
            max={4000}
            onBlur={(event) => {
              const value = Number(memoryBudgetDraft);
              if (value !== settings.memory_token_budget && value >= 200 && value <= 4000) {
                void run(async () => setSettings(await updateAgentMemorySettings({ memory_token_budget: value })));
              }
            }}
            type="number"
            onChange={(event) => setMemoryBudgetDraft(event.target.value)}
            value={memoryBudgetDraft}
          />
          tokens
        </label>
        <label className="text-sm font-medium text-slate-700">
          保留时间
          <select
            className="ml-3 rounded-lg border border-slate-200 px-3 py-2"
            disabled={busy}
            onChange={(event) => void run(async () => setSettings(await updateAgentMemorySettings({ retention_days: Number(event.target.value) })))}
            value={settings.retention_days}
          >
            <option value={30}>30 天</option><option value={90}>90 天</option>
            <option value={180}>180 天</option><option value={365}>1 年</option>
          </select>
        </label>
        <button className="rounded-lg border border-slate-200 bg-white px-3 py-2 text-sm text-slate-700" onClick={() => void downloadAgentMemoryExport()} type="button">导出我的记忆</button>
        {!confirmClear ? (
          <button className="rounded-lg border border-rose-200 bg-white px-3 py-2 text-sm text-rose-700" onClick={() => setConfirmClear(true)} type="button">清空记忆</button>
        ) : (
          <div className="flex items-center gap-2 text-sm text-rose-700">
            <span>先移入回收区，可恢复。</span>
            <button className="rounded-lg bg-rose-600 px-3 py-2 text-white" disabled={busy} onClick={() => void run(async () => { await clearAgentMemories(); setConfirmClear(false); })} type="button">确认清空</button>
            <button onClick={() => setConfirmClear(false)} type="button">取消</button>
          </div>
        )}
      </div>

      <div className="mt-4 rounded-xl border border-slate-200 p-4">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <span className="text-sm font-medium text-slate-700">允许记忆的类型</span>
          <button
            className="text-xs text-indigo-700"
            disabled={busy}
            onClick={() => void run(async () => setSettings(await updateAgentMemorySettings({ allowed_types: memoryTypes.map((item) => item.value) })))}
            type="button"
          >全部允许</button>
        </div>
        <div className="mt-3 flex flex-wrap gap-x-4 gap-y-2">
          {memoryTypes.map((item) => {
            const checked = settings.allowed_types.includes(item.value);
            return (
              <label className="flex items-center gap-2 text-sm text-slate-600" key={item.value}>
                <input
                  checked={checked}
                  disabled={busy}
                  onChange={(event) => {
                    const next = event.target.checked
                      ? [...settings.allowed_types, item.value]
                      : settings.allowed_types.filter((value) => value !== item.value);
                    void run(async () => setSettings(await updateAgentMemorySettings({ allowed_types: next })));
                  }}
                  type="checkbox"
                />
                {item.label}
              </label>
            );
          })}
        </div>
      </div>

      <div className="mt-4 rounded-xl border border-slate-200 bg-slate-50 p-4">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div><p className="text-sm font-medium text-slate-700">语义检索健康</p><p className="mt-1 text-xs text-slate-500">Embedding 模型：{embeddingHealth?.embedding_model || "读取中…"} · 维度 {embeddingHealth?.embedding_dimensions || "—"}</p>{embeddingHealth && <p className={`mt-1 text-xs ${embeddingHealth.provider_available ? "text-emerald-700" : "text-amber-700"}`}>{embeddingHealth.provider_available ? `已向量化 ${embeddingHealth.embedded}/${embeddingHealth.total} 条` : "Provider 不可用，当前只能使用词法检索"}{embeddingHealth.pending > 0 ? ` · 待回填 ${embeddingHealth.pending}` : ""}{embeddingHealth.failed > 0 ? ` · 失败 ${embeddingHealth.failed}` : ""}</p>}</div>
          <div className="flex flex-wrap gap-2"><button className="rounded-lg border border-slate-200 bg-white px-3 py-2 text-xs text-slate-700" disabled={busy} onClick={() => void run(() => createAgentMemoryEmbeddingRun("incremental"))} type="button">增量回填</button><button className="rounded-lg bg-indigo-600 px-3 py-2 text-xs text-white" disabled={busy} onClick={() => void run(() => createAgentMemoryEmbeddingRun("full"))} type="button">全量回填</button><button className="rounded-lg border border-amber-200 bg-amber-50 px-3 py-2 text-xs text-amber-800" disabled={busy} onClick={() => void run(() => runAgentMemoryMaintenance())} type="button">维护记忆</button></div>
        </div>
        {embeddingRuns[0] && <div className="mt-3 rounded-lg bg-white p-3 text-xs text-slate-600"><div className="flex justify-between gap-3"><span>最近任务 · {embeddingRuns[0].mode === "full" ? "全量" : embeddingRuns[0].mode === "maintenance" ? "维护扫描" : "增量"}</span><span>{embeddingRuns[0].status} · {embeddingRuns[0].processed}/{embeddingRuns[0].total}</span></div><div className="mt-2 h-2 overflow-hidden rounded-full bg-slate-200"><div className="h-full rounded-full bg-indigo-500 transition-all" style={{ width: `${embeddingRuns[0].progress}%` }} /></div>{embeddingRuns[0].result_payload && embeddingRuns[0].mode === "maintenance" && <><p className="mt-2">已过期 {String(embeddingRuns[0].result_payload.expired ?? 0)} 条 · 自动修复向量 {String(embeddingRuns[0].result_payload.reembedded ?? 0)} 条 · 待更新向量 {String(embeddingRuns[0].result_payload.stale_embeddings ?? 0)} 条 · 冲突键 {String(embeddingRuns[0].result_payload.conflicting_keys ?? 0)} 组 · 重复内容 {String(embeddingRuns[0].result_payload.duplicate_content_groups ?? 0)} 组</p><MaintenanceFindings busy={busy} onResolve={(action, sourceId, targetId) => void resolveMaintenanceAction(action, sourceId, targetId)} run={embeddingRuns[0]} /></>}{embeddingRuns[0].error && <p className="mt-2 text-rose-700">{embeddingRuns[0].error}</p>}<div className="mt-2 flex gap-3">{(embeddingRuns[0].status === "PENDING" || embeddingRuns[0].status === "RUNNING") && <button className="text-rose-700" disabled={busy} onClick={() => void run(() => cancelAgentMemoryEmbeddingRun(embeddingRuns[0].id))} type="button">取消任务</button>}{(embeddingRuns[0].status === "FAILED" || embeddingRuns[0].status === "CANCELLED") && <button className="text-indigo-700" disabled={busy} onClick={() => void run(() => retryAgentMemoryEmbeddingRun(embeddingRuns[0].id))} type="button">重试失败项</button>}</div></div>}
      </div>

      {error && <p className="mt-4 rounded-xl border border-rose-200 bg-rose-50 p-3 text-sm text-rose-800">{error}</p>}

      <div className="mt-6 flex flex-wrap gap-3">
        <form className="flex min-w-[260px] flex-1 gap-2" onSubmit={(event) => { event.preventDefault(); if (page === 0) void load(0); else setPage(0); }}>
          <input className="min-w-0 flex-1 rounded-xl border border-slate-200 px-4 py-2.5 text-sm" onChange={(event) => setQuery(event.target.value)} placeholder="搜索已保存的记忆" value={query} />
          <button className="rounded-xl bg-slate-900 px-4 py-2.5 text-sm text-white" type="submit">搜索</button>
        </form>
        <select className="rounded-xl border border-slate-200 px-3 py-2.5 text-sm" onChange={(event) => { setPage(0); setType(event.target.value as AgentMemoryType | ""); }} value={type}><option value="">全部类型</option>{memoryTypes.map((item) => <option key={item.value} value={item.value}>{item.label}</option>)}</select>
        <select aria-label="记忆状态" className="rounded-xl border border-slate-200 px-3 py-2.5 text-sm" onChange={(event) => { const next = event.target.value as AgentMemory["status"] | ""; setPage(0); setStatus(next); if (next === "DELETED") setIncludeDeleted(true); }} value={status}><option value="">全部状态</option><option value="ACTIVE">当前有效</option><option value="SUPERSEDED">已被替代</option><option value="EXPIRED">已过时</option><option value="DELETED">回收区</option></select>
        <select aria-label="提取方式" className="rounded-xl border border-slate-200 px-3 py-2.5 text-sm" onChange={(event) => { setPage(0); setExtractionMethod(event.target.value as AgentMemoryExtractionMethod | ""); }} value={extractionMethod}><option value="">全部来源</option><option value="USER">用户录入</option><option value="RULE">规则提取</option><option value="LLM">LLM 提取</option><option value="SUMMARY">会话摘要</option></select>
        <label className="flex items-center gap-2 text-sm text-slate-600"><input checked={includeDeleted} onChange={(event) => { setPage(0); setIncludeDeleted(event.target.checked); }} type="checkbox" />显示回收区</label>
      </div>

      {selected.size > 0 && <button className="mt-4 rounded-lg border border-rose-200 px-3 py-2 text-sm text-rose-700" disabled={busy} onClick={() => void run(() => batchDeleteAgentMemories([...selected]))} type="button">删除已选（{selected.size}）</button>}
      <div className="mt-4 space-y-2">
        {items.length === 0 && <p className="rounded-xl border border-dashed border-slate-200 p-6 text-center text-sm text-slate-500">暂无符合条件的记忆</p>}
        {items.map((item) => (
          <article className={`rounded-xl border p-4 ${item.deleted_at ? "border-slate-200 bg-slate-50 opacity-70" : "border-slate-200 bg-white"}`} key={item.id}>
            <div className="flex items-start gap-3">
              {!item.deleted_at && <input aria-label={`选择 ${item.content}`} checked={selected.has(item.id)} onChange={(event) => setSelected((current) => { const next = new Set(current); if (event.target.checked) next.add(item.id); else next.delete(item.id); return next; })} type="checkbox" />}
              <div className="min-w-0 flex-1">
                <div className="flex flex-wrap items-center gap-2 text-xs"><span className="rounded-full bg-indigo-50 px-2.5 py-1 font-medium text-indigo-700">{typeLabel(item.memory_type)}</span><span className="rounded-full bg-slate-100 px-2 py-1 text-slate-600">{item.memory_key}</span>{item.user_confirmed && <span className="text-emerald-700">来源已验证</span>}{item.extraction_method === "LLM" && <span className="text-violet-700">LLM 提取</span>}{item.pinned && <span className="text-amber-700">已固定</span>}{item.status !== "ACTIVE" && <span className="text-slate-500">{item.status}</span>}</div>
                {editing === item.id ? <textarea autoFocus className="mt-3 min-h-20 w-full rounded-lg border border-slate-200 p-3 text-sm" onChange={(event) => setDraft(event.target.value)} value={draft} /> : <p className="mt-3 text-sm leading-6 text-slate-800">{item.content}</p>}
                <details className="mt-3 text-xs text-slate-500"><summary className="cursor-pointer">查看证据与结构化内容</summary><div className="mt-2 space-y-1 rounded-lg bg-slate-50 p-3"><p>原文证据：{item.source_quote || "未记录"}</p><p>提取方式：{item.extraction_method} · 置信度：{Math.round(item.confidence * 100)}% · 使用 {item.use_count} 次</p><p>更新时间：{item.updated_at.slice(0, 10)} · 到期时间：{item.valid_until ? item.valid_until.slice(0, 10) : "固定记忆"}</p><p>结构化值：{JSON.stringify(item.structured_value)}</p></div></details>
                {historyFor === item.id && <div className="mt-2 rounded-lg border border-slate-200 bg-slate-50 p-3 text-xs text-slate-500">{history.map((version) => <p className="mt-1 first:mt-0" key={version.id}>{version.status} · {version.updated_at.slice(0, 10)} · {version.content}</p>)}</div>}
              </div>
              <div className="flex shrink-0 gap-2 text-sm">
                {item.deleted_at ? <button className="text-indigo-700" disabled={busy} onClick={() => void run(() => restoreAgentMemory(item.id))} type="button">恢复</button> : editing === item.id ? <><button className="text-indigo-700" disabled={busy || !draft.trim()} onClick={() => void run(async () => { await updateAgentMemory(item.id, { content: draft.trim() }); setEditing(null); })} type="button">保存</button><button className="text-slate-500" onClick={() => setEditing(null)} type="button">取消</button></> : <><button className="text-indigo-700" onClick={() => { setEditing(item.id); setDraft(item.content); }} type="button">编辑</button><button className="text-indigo-700" disabled={busy} onClick={() => void run(async () => { setHistory(await getAgentMemoryHistory(item.id)); setHistoryFor(historyFor === item.id ? null : item.id); })} type="button">版本</button><button className="text-amber-700" disabled={busy} onClick={() => void run(() => updateAgentMemory(item.id, { pinned: !item.pinned }))} type="button">{item.pinned ? "取消固定" : "固定"}</button><button className="text-slate-600" disabled={busy} onClick={() => void run(() => markAgentMemoryOutdated(item.id))} type="button">标记过时</button><button className="text-rose-700" disabled={busy} onClick={() => void run(() => deleteAgentMemory(item.id))} type="button">删除</button></>}
              </div>
            </div>
          </article>
        ))}
      </div>
      {(total > pageSize || page > 0) && <div className="mt-4 flex items-center justify-between gap-3 text-sm text-slate-500"><button className="rounded-lg border border-slate-200 px-3 py-2 disabled:opacity-40" disabled={page === 0 || busy} onClick={() => setPage((current) => Math.max(0, current - 1))} type="button">上一页</button><span>第 {page + 1} 页 · {total} 条</span><button className="rounded-lg border border-slate-200 px-3 py-2 disabled:opacity-40" disabled={!hasMore || busy} onClick={() => setPage((current) => current + 1)} type="button">下一页</button></div>}
      <p className="mt-3 text-xs text-slate-500">当前查询共 {total} 条记忆，本页 {activeItems.length} 条有效记忆。回收区内容不会进入 Agent 上下文。</p>
    </section>
  );
}
