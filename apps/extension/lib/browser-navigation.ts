// Shared by BOSS delivery/search and the sequential Zhaopin detail collector.
export async function waitForTabComplete(tabId: number): Promise<void> {
  const deadline = Date.now() + 30_000;
  while (Date.now() < deadline) {
    if ((await browser.tabs.get(tabId)).status === "complete") return;
    await new Promise((resolve) => setTimeout(resolve, 250));
  }
  throw new Error("招聘页面加载超时，请检查页面或网络后继续");
}
