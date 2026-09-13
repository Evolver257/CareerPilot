"use client";

import { useEffect, useMemo, useState } from "react";

import { MemorySettingsPanel } from "../../components/memory-settings-panel";
import { MCPSettingsPanel } from "../../components/mcp-settings-panel";
import { KnowledgeBaseMaintenancePanel } from "../../components/knowledge-base-maintenance-panel";

import {
  deleteLLMProvider,
  getRecruitmentPlatforms,
  getLLMSettings,
  saveLLMProvider,
  setActiveLLMProvider,
  testLLMConnection,
  testSavedLLMProvider,
  type ActiveLLMProvider,
type LLMProviderName,
  type LLMSettings,
  type RecruitmentPlatform,
} from "../../lib/api";

type BuildInfo = { version: string; build_time: string | null };

const providerDefaults: Record<LLMProviderName, { label: string; model: string; baseUrl: string }> = {
  openai: {
    label: "OpenAI 兼容格式",
    model: "gpt-4o-mini",
    baseUrl: "https://api.openai.com/v1",
  },
  anthropic: {
    label: "Anthropic Messages 格式",
    model: "claude-3-5-haiku-latest",
    baseUrl: "https://api.anthropic.com",
  },
};

function providerLabel(provider: ActiveLLMProvider): string {
  if (provider === "mock") return "本地 Mock";
  return providerDefaults[provider].label;
}

export default function SettingsPage() {
  const [settings, setSettings] = useState<LLMSettings | null>(null);
  const [provider, setProvider] = useState<LLMProviderName>("openai");
  const [apiKey, setApiKey] = useState("");
  const [model, setModel] = useState(providerDefaults.openai.model);
  const [baseUrl, setBaseUrl] = useState(providerDefaults.openai.baseUrl);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [testingProvider, setTestingProvider] = useState<LLMProviderName | "form" | null>(null);
  const [maintaining, setMaintaining] = useState<ActiveLLMProvider | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [recruitmentPlatforms, setRecruitmentPlatforms] = useState<RecruitmentPlatform[]>([]);
  const [buildInfo, setBuildInfo] = useState<BuildInfo | null>(null);

  const configuredProvider = useMemo(
    () => settings?.providers.find((item) => item.provider === provider),
    [provider, settings],
  );
  const testing = testingProvider !== null;

  useEffect(() => {
    void loadSettings();
    getRecruitmentPlatforms().then(setRecruitmentPlatforms).catch(() => setRecruitmentPlatforms([]));
    fetch("/api/build-info", { cache: "no-store" })
      .then((response) => (response.ok ? response.json() as Promise<BuildInfo> : null))
      .then(setBuildInfo)
      .catch(() => setBuildInfo(null));
  }, []);

  useEffect(() => {
    const defaults = providerDefaults[provider];
    const saved = settings?.providers.find((item) => item.provider === provider);
    setModel(saved?.model || defaults.model);
    setBaseUrl(saved?.base_url || defaults.baseUrl);
    setApiKey("");
  }, [provider, settings]);

  async function loadSettings() {
    setLoading(true);
    try {
      setSettings(await getLLMSettings());
      setError(null);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "无法加载 LLM 设置，请确认 API 服务已启动。");
    } finally {
      setLoading(false);
    }
  }

  async function handleSave() {
    if (!apiKey.trim()) {
      setError("请输入 API key。保存后系统不会再次显示完整密钥。");
      return;
    }
    setSaving(true);
    setError(null);
    setNotice(null);
    try {
      const next = await saveLLMProvider(provider, {
        api_key: apiKey.trim(),
        model: model.trim(),
        base_url: baseUrl.trim(),
      });
      setSettings(next);
      setApiKey("");
      setNotice(`${providerLabel(provider)}已保存，并已切换为当前调用 Provider。`);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "LLM 配置保存失败。");
    } finally {
      setSaving(false);
    }
  }

  async function handleTestConnection() {
    if (!apiKey.trim() && !configuredProvider) {
      setError("请先输入 API key，或先保存一份该 Provider 配置。");
      return;
    }
    setTestingProvider("form");
    setError(null);
    setNotice(null);
    try {
      const result = apiKey.trim()
        ? await testLLMConnection({
            provider,
            api_key: apiKey.trim(),
            model: model.trim(),
            base_url: baseUrl.trim(),
          })
        : await testSavedLLMProvider(provider);
      setNotice(`${providerLabel(provider)}连接成功（${result.latency_ms} ms），未修改已保存配置。`);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "LLM 连接测试失败，请检查配置。 ");
    } finally {
      setTestingProvider(null);
    }
  }

  async function handleTestSavedProvider(nextProvider: LLMProviderName) {
    setTestingProvider(nextProvider);
    setError(null);
    setNotice(null);
    try {
      const result = await testSavedLLMProvider(nextProvider);
      setNotice(`${providerLabel(nextProvider)}连接成功（${result.latency_ms} ms），未修改已保存配置。`);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "已保存 Provider 连接测试失败，请检查配置。 ");
    } finally {
      setTestingProvider(null);
    }
  }

  async function handleSetActive(nextProvider: ActiveLLMProvider) {
    setMaintaining(nextProvider);
    setError(null);
    setNotice(null);
    try {
      setSettings(await setActiveLLMProvider(nextProvider));
      setNotice(`已切换到${providerLabel(nextProvider)}。`);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "当前 Provider 切换失败。");
    } finally {
      setMaintaining(null);
    }
  }

  async function handleDelete(nextProvider: LLMProviderName) {
    if (!window.confirm(`确定删除已保存的 ${providerLabel(nextProvider)} API key 吗？`)) return;
    setMaintaining(nextProvider);
    setError(null);
    setNotice(null);
    try {
      await deleteLLMProvider(nextProvider);
      setSettings(await getLLMSettings());
      setNotice("API key 已删除，后续调用将回到本地 Mock 或其他当前 Provider。");
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "API key 删除失败。");
    } finally {
      setMaintaining(null);
    }
  }

  return (
    <div className="mx-auto max-w-5xl space-y-8">
      <header className="flex flex-wrap items-end justify-between gap-4">
        <div>
          <p className="eyebrow">模型、数据与连接</p>
          <h1 className="mt-3 text-3xl font-semibold tracking-tight">系统设置</h1>
          <p className="mt-3 max-w-2xl text-slate-500">
            管理模型服务、岗位知识库、长期记忆和外部工具连接。API 密钥只发送到本地服务，保存后仅展示末 4 位。
          </p>
        </div>
        <span className="rounded-full bg-indigo-50 px-4 py-2 text-sm font-medium text-indigo-700">
          当前：{loading ? "读取中…" : providerLabel(settings?.active_provider ?? "mock")}
        </span>
      </header>

      {error && <div className="rounded-xl border border-rose-200 bg-rose-50 p-4 text-rose-800">{error}</div>}
      {notice && <div className="rounded-xl border border-emerald-200 bg-emerald-50 p-4 text-emerald-800">{notice}</div>}

      <KnowledgeBaseMaintenancePanel />
      <MemorySettingsPanel />
      <MCPSettingsPanel />

      <section className="panel">
        <div>
          <p className="eyebrow">添加 Provider</p>
          <h2 className="mt-2 text-xl font-semibold">连接自己的模型服务</h2>
          <p className="mt-2 text-sm leading-6 text-slate-500">
            OpenAI 使用 Chat Completions 兼容格式，Anthropic 使用 Messages 格式；Base URL 可填写兼容网关地址。
          </p>
        </div>
        <div className="mt-6 grid gap-4 md:grid-cols-2">
          <label className="text-sm font-medium text-slate-700" htmlFor="llm-provider">
            Provider
            <select
              className="mt-2 w-full rounded-xl border border-slate-200 px-4 py-3 outline-none focus:border-indigo-500 focus:ring-4 focus:ring-indigo-100"
              id="llm-provider"
              onChange={(event) => setProvider(event.target.value as LLMProviderName)}
              value={provider}
            >
              <option value="openai">OpenAI 兼容格式</option>
              <option value="anthropic">Anthropic Messages 格式</option>
            </select>
          </label>
          <label className="text-sm font-medium text-slate-700" htmlFor="llm-model">
            模型名称
            <input className="mt-2 w-full rounded-xl border border-slate-200 px-4 py-3 outline-none focus:border-indigo-500 focus:ring-4 focus:ring-indigo-100" id="llm-model" onChange={(event) => setModel(event.target.value)} placeholder={providerDefaults[provider].model} value={model} />
          </label>
          <label className="text-sm font-medium text-slate-700 md:col-span-2" htmlFor="llm-api-key">
            API key
            <input autoComplete="new-password" className="mt-2 w-full rounded-xl border border-slate-200 px-4 py-3 font-mono outline-none focus:border-indigo-500 focus:ring-4 focus:ring-indigo-100" id="llm-api-key" onChange={(event) => setApiKey(event.target.value)} placeholder={configuredProvider ? `已配置（${configuredProvider.api_key_hint}），输入新 key 可替换` : "输入后保存，系统不会回显完整密钥"} type="password" value={apiKey} />
          </label>
          <label className="text-sm font-medium text-slate-700 md:col-span-2" htmlFor="llm-base-url">
            Base URL（可选）
            <input className="mt-2 w-full rounded-xl border border-slate-200 px-4 py-3 font-mono text-sm outline-none focus:border-indigo-500 focus:ring-4 focus:ring-indigo-100" id="llm-base-url" onChange={(event) => setBaseUrl(event.target.value)} placeholder={providerDefaults[provider].baseUrl} value={baseUrl} />
          </label>
        </div>
        <div className="mt-5 flex flex-wrap items-center gap-3">
          <button className="rounded-xl bg-indigo-600 px-5 py-3 font-medium text-white transition hover:bg-indigo-700 disabled:cursor-not-allowed disabled:opacity-50" disabled={saving || loading} onClick={() => void handleSave()} type="button">
            {saving ? "保存中…" : configuredProvider ? "替换并启用" : "保存并启用"}
          </button>
          <button className="rounded-xl border border-indigo-200 px-5 py-3 font-medium text-indigo-700 transition hover:bg-indigo-50 disabled:cursor-not-allowed disabled:opacity-50" disabled={saving || testing || loading} onClick={() => void handleTestConnection()} type="button">
            {testingProvider === "form" ? "测试中…" : "测试连接"}
          </button>
          <span className="text-sm text-slate-500">测试不会保存或修改配置；有已保存 key 时可直接测试。</span>
        </div>
      </section>

      <section className="panel">
        <div>
          <p className="eyebrow">招聘平台</p>
          <h2 className="mt-2 text-xl font-semibold">已接入的平台</h2>
          <p className="mt-2 text-sm leading-6 text-slate-500">平台连接使用浏览器当前可见页面；账号、Cookie 和验证码仍由用户在招聘网站完成。</p>
        </div>
        <div className="mt-5 grid gap-3 md:grid-cols-2">
          {recruitmentPlatforms.map((item) => (
            <div className="rounded-xl border border-slate-200 bg-slate-50 p-4" key={item.id}>
              <div className="flex items-center justify-between gap-3"><p className="font-medium text-slate-800">{item.name}</p><span className="rounded-full bg-emerald-100 px-2.5 py-1 text-xs font-medium text-emerald-700">{item.enabled ? "已启用" : "未启用"}</span></div>
              <p className="mt-2 text-xs text-slate-500">{item.browser_session_required ? "需要浏览器可见页面" : "支持服务端搜索"} · {Object.entries(item.capabilities).filter(([, enabled]) => enabled).map(([key]) => key).join("、")}</p>
            </div>
          ))}
        </div>
      </section>

      <section className="grid gap-5 md:grid-cols-2">
        <article className={`panel ${settings?.active_provider === "mock" ? "border-indigo-300 ring-2 ring-indigo-100" : ""}`}>
          <div className="flex items-start justify-between gap-4">
            <div>
              <p className="eyebrow">默认安全模式</p>
              <h2 className="mt-2 text-xl font-semibold">本地 Mock</h2>
              <p className="mt-2 text-sm leading-6 text-slate-500">不调用外部模型，适合离线开发、演示和验证流程。</p>
            </div>
            {settings?.active_provider === "mock" && <span className="rounded-full bg-indigo-50 px-3 py-1 text-xs font-medium text-indigo-700">当前使用</span>}
          </div>
          {settings?.active_provider !== "mock" && <button className="mt-5 rounded-xl border border-slate-200 px-4 py-2 text-sm font-medium text-slate-700 transition hover:border-indigo-300 hover:text-indigo-700 disabled:opacity-50" disabled={maintaining !== null} onClick={() => void handleSetActive("mock")} type="button">切换到 Mock</button>}
        </article>

        {settings?.providers.map((item) => (
          <article className={`panel ${item.is_active ? "border-indigo-300 ring-2 ring-indigo-100" : ""}`} key={item.provider}>
            <div className="flex items-start justify-between gap-4">
              <div>
                <p className="eyebrow">已配置 Provider</p>
                <h2 className="mt-2 text-xl font-semibold">{providerLabel(item.provider)}</h2>
              </div>
              {item.is_active && <span className="rounded-full bg-emerald-50 px-3 py-1 text-xs font-medium text-emerald-700">当前使用</span>}
            </div>
            <dl className="mt-5 space-y-2 text-sm">
              <div className="flex justify-between gap-4"><dt className="text-slate-500">API key</dt><dd className="font-mono text-slate-700">{item.api_key_hint}</dd></div>
              <div className="flex justify-between gap-4"><dt className="text-slate-500">模型</dt><dd className="max-w-[70%] truncate text-right text-slate-700">{item.model}</dd></div>
              <div className="flex justify-between gap-4"><dt className="text-slate-500">Base URL</dt><dd className="max-w-[70%] truncate text-right font-mono text-xs text-slate-500">{item.base_url}</dd></div>
            </dl>
            <div className="mt-5 flex flex-wrap gap-3">
              <button className="rounded-xl border border-indigo-200 px-4 py-2 text-sm font-medium text-indigo-700 transition hover:bg-indigo-50 disabled:cursor-not-allowed disabled:opacity-50" disabled={testing || maintaining !== null} onClick={() => void handleTestSavedProvider(item.provider)} type="button">
                {testingProvider === item.provider ? "测试中…" : "测试连接"}
              </button>
              {!item.is_active && <button className="rounded-xl border border-indigo-200 px-4 py-2 text-sm font-medium text-indigo-700 transition hover:bg-indigo-50 disabled:opacity-50" disabled={maintaining !== null} onClick={() => void handleSetActive(item.provider)} type="button">设为当前</button>}
              <button className="rounded-xl border border-rose-200 px-4 py-2 text-sm font-medium text-rose-700 transition hover:bg-rose-50 disabled:opacity-50" disabled={maintaining !== null || testing} onClick={() => void handleDelete(item.provider)} type="button">删除 key</button>
            </div>
          </article>
        ))}
      </section>

      <section className="rounded-2xl border border-amber-200 bg-amber-50 p-5 text-sm leading-6 text-amber-800">
        <p className="font-semibold">安全提示</p>
        <p className="mt-1">API key 会在服务端加密保存，接口和页面都不会返回完整密钥。部署到生产环境时，请为 API 服务设置独立且足够随机的 LLM_ENCRYPTION_KEY，并不要把 key 提交到代码仓库。</p>
      </section>

      <section className="rounded-2xl border border-slate-200 bg-slate-50 p-4 text-xs text-slate-500">
        <p className="font-medium text-slate-700">系统版本</p>
        <p className="mt-1">前端 {buildInfo?.version ?? "未读取"}{buildInfo?.build_time ? ` · 构建于 ${buildInfo.build_time}` : ""}</p>
      </section>
    </div>
  );
}
