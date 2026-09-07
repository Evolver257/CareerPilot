"use client";

import { useEffect, useState } from "react";

import {
  createMCPConnection,
  deleteMCPConnection,
  discoverMCPTools,
  getMCPConnections,
  updateMCPConnection,
  type MCPConnection,
} from "../lib/api";

export function MCPSettingsPanel() {
  const [connections, setConnections] = useState<MCPConnection[]>([]);
  const [open, setOpen] = useState(false);
  const [name, setName] = useState("");
  const [namespace, setNamespace] = useState("");
  const [endpoint, setEndpoint] = useState("");
  const [token, setToken] = useState("");
  const [allowedTools, setAllowedTools] = useState("*");
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [pendingDelete, setPendingDelete] = useState<string | null>(null);

  async function load() {
    try {
      setConnections(await getMCPConnections());
      setError(null);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "MCP 连接加载失败");
    }
  }

  useEffect(() => { void load(); }, []);

  async function run(key: string, action: () => Promise<unknown>, success: string) {
    setBusy(key); setError(null); setNotice(null);
    try { await action(); await load(); setNotice(success); }
    catch (reason) { setError(reason instanceof Error ? reason.message : "MCP 操作失败"); }
    finally { setBusy(null); }
  }

  async function add() {
    if (!name.trim() || !namespace.trim() || !endpoint.trim()) {
      setError("请填写连接名称、命名空间和 HTTPS 地址。"); return;
    }
    await run("create", () => createMCPConnection({
      name: name.trim(), namespace: namespace.trim(), transport: "streamable_http",
      endpoint: endpoint.trim(),
      credentials: token.trim() ? { Authorization: `Bearer ${token.trim()}` } : {},
      permission_scopes: ["external.read"],
      allowed_tools: allowedTools.split(",").map((item) => item.trim()).filter(Boolean),
    }), "连接已保存，默认保持关闭。请确认权限后再启用并发现工具。");
    setName(""); setNamespace(""); setEndpoint(""); setToken("");
  }

  return (
    <section className="panel" aria-labelledby="mcp-settings-title">
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div><p className="eyebrow">开发者扩展</p><h2 className="mt-2 text-xl font-semibold" id="mcp-settings-title">MCP 工具连接</h2><p className="mt-2 max-w-2xl text-sm leading-6 text-slate-500">连接按用户隔离，默认关闭并采用最小只读权限。服务描述和返回内容都会按不可信数据处理。</p></div>
        <button className="rounded-xl border border-slate-200 px-4 py-2 text-sm text-slate-700" onClick={() => setOpen((value) => !value)} type="button">{open ? "收起" : "管理连接"}</button>
      </div>
      {open && <>
        {error && <p className="mt-4 rounded-xl border border-rose-200 bg-rose-50 p-3 text-sm text-rose-800">{error}</p>}
        {notice && <p className="mt-4 rounded-xl border border-emerald-200 bg-emerald-50 p-3 text-sm text-emerald-800">{notice}</p>}
        <div className="mt-5 grid gap-3 rounded-xl border border-slate-200 bg-slate-50 p-4 md:grid-cols-2">
          <input className="rounded-xl border border-slate-200 px-3 py-2.5 text-sm" onChange={(event) => setName(event.target.value)} placeholder="连接名称" value={name} />
          <input className="rounded-xl border border-slate-200 px-3 py-2.5 text-sm" onChange={(event) => setNamespace(event.target.value.replace(/[^a-zA-Z0-9_-]/g, ""))} placeholder="命名空间，如 company_kb" value={namespace} />
          <input className="rounded-xl border border-slate-200 px-3 py-2.5 text-sm md:col-span-2" onChange={(event) => setEndpoint(event.target.value)} placeholder="https://example.com/mcp" value={endpoint} />
          <input autoComplete="new-password" className="rounded-xl border border-slate-200 px-3 py-2.5 text-sm" onChange={(event) => setToken(event.target.value)} placeholder="Bearer Token（可选，仅加密保存）" type="password" value={token} />
          <input className="rounded-xl border border-slate-200 px-3 py-2.5 text-sm" onChange={(event) => setAllowedTools(event.target.value)} placeholder="允许工具，逗号分隔" value={allowedTools} />
          <button className="rounded-xl bg-indigo-600 px-4 py-2.5 text-sm font-medium text-white disabled:opacity-50 md:col-span-2" disabled={busy !== null} onClick={() => void add()} type="button">{busy === "create" ? "保存中…" : "保存连接"}</button>
        </div>
        <div className="mt-4 space-y-3">
          {connections.length === 0 && <p className="rounded-xl border border-dashed border-slate-200 p-5 text-center text-sm text-slate-500">尚未配置 MCP 连接</p>}
          {connections.map((item) => <article className="rounded-xl border border-slate-200 bg-white p-4" key={item.id}>
            <div className="flex flex-wrap items-start justify-between gap-3"><div><div className="flex items-center gap-2"><h3 className="font-medium text-slate-800">{item.name}</h3><span className={`rounded-full px-2 py-0.5 text-xs ${item.enabled ? "bg-emerald-50 text-emerald-700" : "bg-slate-100 text-slate-500"}`}>{item.status}</span></div><p className="mt-1 font-mono text-xs text-slate-500">mcp:{item.namespace}:* · {item.endpoint}</p><p className="mt-2 text-xs text-slate-500">权限：{item.permission_scopes.join("、") || "无"} · {item.credentials_hint || "未配置凭据"}</p></div>
              <div className="flex flex-wrap gap-2 text-sm"><button className="rounded-lg border border-indigo-200 px-3 py-2 text-indigo-700" disabled={busy !== null} onClick={() => void run(item.id, () => updateMCPConnection(item.id, { enabled: !item.enabled }), item.enabled ? "连接已暂停。" : "连接已启用。") } type="button">{item.enabled ? "暂停" : "启用"}</button><button className="rounded-lg border border-slate-200 px-3 py-2 text-slate-700 disabled:opacity-50" disabled={!item.enabled || busy !== null} onClick={() => void run(item.id, () => discoverMCPTools(item.id), "工具目录已刷新。") } type="button">发现工具</button>{pendingDelete === item.id ? <><button className="rounded-lg bg-rose-600 px-3 py-2 text-white" disabled={busy !== null} onClick={() => void run(item.id, async () => { await deleteMCPConnection(item.id); setPendingDelete(null); }, "连接已删除。") } type="button">确认删除</button><button onClick={() => setPendingDelete(null)} type="button">取消</button></> : <button className="rounded-lg border border-rose-200 px-3 py-2 text-rose-700" onClick={() => setPendingDelete(item.id)} type="button">删除</button>}</div>
            </div>
          </article>)}
        </div>
      </>}
    </section>
  );
}
