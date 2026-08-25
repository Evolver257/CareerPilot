import type { ActionMessage, ActionResultMessage } from "../lib/protocol";

const API_WS_BASE = "ws://localhost:8010/api/browser-tasks/ws/";
const sockets = new Map<string, WebSocket>();
const activeTabs = new Map<string, number>();

export default defineBackground(() => {
  browser.tabs.onUpdated.addListener(async (tabId, changeInfo, tab) => {
    if (changeInfo.status !== "complete" || !tab.url) return;
    const taskId = new URL(tab.url).searchParams.get("task");
    if (taskId) {
      activeTabs.set(taskId, tabId);
      connectTask(taskId, tabId);
    }
  });

  browser.runtime.onMessage.addListener(async (message: ActionResultMessage, sender) => {
    if (message.type !== "ACTION_RESULT") return;
    const tabId = sender.tab?.id;
    const taskId = [...activeTabs.entries()].find(([, activeTabId]) => activeTabId === tabId)?.[0];
    if (!taskId) return;
    sockets.get(taskId)?.send(JSON.stringify(message));
  });
});

function connectTask(taskId: string, tabId: number) {
  if (sockets.has(taskId)) return;
  const socket = new WebSocket(`${API_WS_BASE}${taskId}`);
  sockets.set(taskId, socket);
  socket.addEventListener("open", () => socket.send(JSON.stringify({ type: "EXTENSION_HELLO", extension_version: "phase8", tab_url: "" })));
  socket.addEventListener("message", async (event) => {
    const message = JSON.parse(String(event.data)) as ActionMessage;
    if (message.type !== "ACTION" && message.type !== "REQUEST_USER_ACTION") return;
    if (message.action.action === "NAVIGATE" && message.action.url) {
      await browser.tabs.update(tabId, { url: message.action.url });
      socket.send(JSON.stringify({ type: "ACTION_RESULT", action_id: message.action.id, success: true, data: { url: message.action.url }, page_state: "NAVIGATED" }));
      return;
    }
    await browser.tabs.sendMessage(tabId, message);
  });
  socket.addEventListener("close", () => sockets.delete(taskId));
}
