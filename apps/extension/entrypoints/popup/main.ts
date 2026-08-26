import { isBossPageUrl, type BossVisibleJob } from "../../lib/platforms/boss";
import type { BossCaptureResponse } from "../../lib/protocol";

const API_BASE_URL = "http://localhost:8010";
const button = document.querySelector<HTMLButtonElement>("#capture");
const status = document.querySelector<HTMLDivElement>("#status");

button?.addEventListener("click", () => void capture());

async function capture(): Promise<void> {
  if (!button || !status) return;
  button.disabled = true;
  status.className = "";
  status.textContent = "读取当前页面…";
  try {
    const tabs = await browser.tabs.query({ active: true, currentWindow: true });
    const tab = tabs[0];
    if (!tab?.id || !tab.url || !isBossPageUrl(tab.url)) throw new Error("请先打开 BOSS 直聘职位列表或详情页。");
    const result = await browser.tabs.sendMessage(tab.id, { type: "CAPTURE_BOSS_VISIBLE" }) as BossCaptureResponse;
    if (!result.success) throw new Error(result.error || `页面状态：${result.page_state}`);
    if (result.jobs.length === 0) throw new Error("当前可见页面没有识别到职位卡片。");
    const imported = await importJobs(result.page_url, result.jobs);
    status.className = "ok";
    status.textContent = `已导入 ${imported.created} 条，重复 ${imported.duplicates} 条。`;
  } catch (error) {
    status.className = "error";
    status.textContent = error instanceof Error ? error.message : "采集失败。";
  } finally {
    button.disabled = false;
  }
}

async function importJobs(pageUrl: string, jobs: BossVisibleJob[]): Promise<{ created: number; duplicates: number }> {
  const response = await fetch(`${API_BASE_URL}/api/platforms/boss/import-visible`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ page_url: pageUrl, jobs }),
  });
  if (!response.ok) {
    const body = (await response.json().catch(() => ({}))) as { detail?: string };
    throw new Error(body.detail || `导入失败：${response.status}`);
  }
  return response.json() as Promise<{ created: number; duplicates: number }>;
}
