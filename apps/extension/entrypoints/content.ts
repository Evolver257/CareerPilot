import { findSemanticElement, type ActionMessage, type ActionResultMessage } from "../lib/protocol";

export default defineContentScript({
  matches: ["http://localhost:3000/mock-platform/*"],
  runAt: "document_idle",
  main() {
    browser.runtime.onMessage.addListener(async (message: ActionMessage) => {
      if (message.type !== "ACTION" && message.type !== "REQUEST_USER_ACTION") return;
      const result: ActionResultMessage = await executeAction(message);
      await browser.runtime.sendMessage(result);
    });
  },
});

async function executeAction(message: ActionMessage): Promise<ActionResultMessage> {
  const action = message.action;
  try {
    if (action.action === "CLICK") {
      const element = findSemanticElement(action);
      if (!(element instanceof HTMLElement)) throw new Error("Semantic target not found");
      element.click();
    } else if (action.action === "TYPE") {
      const element = findSemanticElement(action);
      if (!(element instanceof HTMLInputElement || element instanceof HTMLTextAreaElement)) throw new Error("Type target not found");
      element.value = action.value ?? "";
      element.dispatchEvent(new Event("input", { bubbles: true }));
    } else if (action.action === "SCROLL") {
      window.scrollTo({ top: document.body.scrollHeight, behavior: "instant" });
    } else if (action.action === "WAIT") {
      await new Promise((resolve) => window.setTimeout(resolve, action.wait_ms ?? 300));
    } else if (action.action === "REQUEST_USER_ACTION") {
      return { type: "ACTION_RESULT", action_id: action.id, success: true, data: { acknowledged: true }, page_state: document.title };
    }
    return { type: "ACTION_RESULT", action_id: action.id, success: true, data: { text: document.body.innerText.slice(0, 1000) }, page_state: document.title };
  } catch (error) {
    return { type: "ACTION_RESULT", action_id: action.id, success: false, error: error instanceof Error ? error.message : "Action failed", page_state: document.title };
  }
}
