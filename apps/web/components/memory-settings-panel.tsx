"use client";

import { useEffect, useMemo, useState } from "react";

import {
  batchDeleteAgentMemories,
  clearAgentMemories,
  deleteAgentMemory,
  downloadAgentMemoryExport,
  getAgentMemories,
  getAgentMemoryCandidates,
  getAgentMemorySettings,
  resolveAgentMemoryCandidate,
  restoreAgentMemory,
  updateAgentMemory,
  updateAgentMemorySettings,
  type AgentMemory,
  type AgentMemoryCandidate,
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

export function MemorySettingsPanel() {
  const [settings, setSettings] = useState<AgentMemorySettings | null>(null);
  const [items, setItems] = useState<AgentMemory[]>([]);
  const [candidates, setCandidates] = useState<AgentMemoryCandidate[]>([]);
  const [query, setQuery] = useState("");
  const [type, setType] = useState<AgentMemoryType | "">("");
  const [includeDeleted, setIncludeDeleted] = useState(false);
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [editing, setEditing] = useState<string | null>(null);
  const [draft, setDraft] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [confirmClear, setConfirmClear] = useState(false);

  const activeItems = useMemo(() => items.filter((item) => !item.deleted_at), [items]);

  async function load() {
    try {
      const [nextSettings, memories, pending] = await Promise.all([
        getAgentMemorySettings(),
        getAgentMemories({ query, memoryType: type, includeDeleted }),
        getAgentMemoryCandidates(),
      ]);
      setSettings(nextSettings);
      setItems(memories.items);
      setCandidates(pending.items);
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
  }, [type, includeDeleted]);

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
            默认关闭。开启后只提取明确表达的职业目标和偏好，并先放入待确认区；密钥、联系方式和身份信息不会保存。
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

      {error && <p className="mt-4 rounded-xl border border-rose-200 bg-rose-50 p-3 text-sm text-rose-800">{error}</p>}

      {candidates.length > 0 && (
        <div className="mt-6">
          <h3 className="font-semibold">待你确认 <span className="text-sm font-normal text-slate-500">({candidates.length})</span></h3>
          <div className="mt-3 space-y-2">
            {candidates.map((candidate) => (
              <div className="flex flex-wrap items-center justify-between gap-3 rounded-xl border border-amber-200 bg-amber-50 p-4" key={candidate.id}>
                <div><span className="text-xs font-medium text-amber-700">{typeLabel(candidate.memory_type)}</span><p className="mt-1 text-sm text-slate-800">{candidate.content}</p></div>
                <div className="flex gap-2"><button className="rounded-lg bg-indigo-600 px-3 py-2 text-sm text-white" disabled={busy} onClick={() => void run(() => resolveAgentMemoryCandidate(candidate.id, true))} type="button">确认保存</button><button className="rounded-lg border border-slate-200 bg-white px-3 py-2 text-sm" disabled={busy} onClick={() => void run(() => resolveAgentMemoryCandidate(candidate.id, false))} type="button">忽略</button></div>
              </div>
            ))}
          </div>
        </div>
      )}

      <div className="mt-6 flex flex-wrap gap-3">
        <form className="flex min-w-[260px] flex-1 gap-2" onSubmit={(event) => { event.preventDefault(); void load(); }}>
          <input className="min-w-0 flex-1 rounded-xl border border-slate-200 px-4 py-2.5 text-sm" onChange={(event) => setQuery(event.target.value)} placeholder="搜索已保存的记忆" value={query} />
          <button className="rounded-xl bg-slate-900 px-4 py-2.5 text-sm text-white" type="submit">搜索</button>
        </form>
        <select className="rounded-xl border border-slate-200 px-3 py-2.5 text-sm" onChange={(event) => setType(event.target.value as AgentMemoryType | "")} value={type}><option value="">全部类型</option>{memoryTypes.map((item) => <option key={item.value} value={item.value}>{item.label}</option>)}</select>
        <label className="flex items-center gap-2 text-sm text-slate-600"><input checked={includeDeleted} onChange={(event) => setIncludeDeleted(event.target.checked)} type="checkbox" />显示回收区</label>
      </div>

      {selected.size > 0 && <button className="mt-4 rounded-lg border border-rose-200 px-3 py-2 text-sm text-rose-700" disabled={busy} onClick={() => void run(() => batchDeleteAgentMemories([...selected]))} type="button">删除已选（{selected.size}）</button>}
      <div className="mt-4 space-y-2">
        {items.length === 0 && <p className="rounded-xl border border-dashed border-slate-200 p-6 text-center text-sm text-slate-500">暂无符合条件的记忆</p>}
        {items.map((item) => (
          <article className={`rounded-xl border p-4 ${item.deleted_at ? "border-slate-200 bg-slate-50 opacity-70" : "border-slate-200 bg-white"}`} key={item.id}>
            <div className="flex items-start gap-3">
              {!item.deleted_at && <input aria-label={`选择 ${item.content}`} checked={selected.has(item.id)} onChange={(event) => setSelected((current) => { const next = new Set(current); if (event.target.checked) next.add(item.id); else next.delete(item.id); return next; })} type="checkbox" />}
              <div className="min-w-0 flex-1">
                <div className="flex flex-wrap items-center gap-2 text-xs"><span className="rounded-full bg-indigo-50 px-2.5 py-1 font-medium text-indigo-700">{typeLabel(item.memory_type)}</span>{item.user_confirmed && <span className="text-emerald-700">已确认</span>}{item.deleted_at && <span className="text-slate-500">回收区</span>}</div>
                {editing === item.id ? <textarea autoFocus className="mt-3 min-h-20 w-full rounded-lg border border-slate-200 p-3 text-sm" onChange={(event) => setDraft(event.target.value)} value={draft} /> : <p className="mt-3 text-sm leading-6 text-slate-800">{item.content}</p>}
              </div>
              <div className="flex shrink-0 gap-2 text-sm">
                {item.deleted_at ? <button className="text-indigo-700" disabled={busy} onClick={() => void run(() => restoreAgentMemory(item.id))} type="button">恢复</button> : editing === item.id ? <><button className="text-indigo-700" disabled={busy || !draft.trim()} onClick={() => void run(async () => { await updateAgentMemory(item.id, { content: draft.trim() }); setEditing(null); })} type="button">保存</button><button className="text-slate-500" onClick={() => setEditing(null)} type="button">取消</button></> : <><button className="text-indigo-700" onClick={() => { setEditing(item.id); setDraft(item.content); }} type="button">编辑</button><button className="text-rose-700" disabled={busy} onClick={() => void run(() => deleteAgentMemory(item.id))} type="button">删除</button></>}
              </div>
            </div>
          </article>
        ))}
      </div>
      <p className="mt-3 text-xs text-slate-500">共 {activeItems.length} 条当前可用记忆。回收区内容不会进入 Agent 上下文。</p>
    </section>
  );
}
