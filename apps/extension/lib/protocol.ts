export type BrowserAction = {
  id: string;
  action: "NAVIGATE" | "CLICK" | "TYPE" | "EXTRACT" | "SCROLL" | "WAIT" | "CHECK_STATE" | "SCREENSHOT" | "REQUEST_USER_ACTION";
  target?: { strategy: string; name?: string | null; selector?: string | null } | null;
  value?: string | null;
  url?: string | null;
  wait_ms?: number;
  metadata?: Record<string, unknown>;
};

export type ActionMessage = {
  type: "ACTION" | "REQUEST_USER_ACTION";
  task_id: string;
  sequence?: number;
  action: BrowserAction;
};

export type ActionResultMessage = {
  type: "ACTION_RESULT";
  action_id: string;
  success: boolean;
  data?: Record<string, unknown>;
  page_state?: string;
  error?: string;
};

export function findSemanticElement(action: BrowserAction): Element | null {
  if (action.target?.selector) return document.querySelector(action.target.selector);
  const name = action.target?.name?.trim().toLocaleLowerCase();
  if (!name) return null;
  return [...document.querySelectorAll("button, a, input, textarea, [role='button']")].find((element) => {
    const text = (element.textContent || (element as HTMLInputElement).value || "").trim().toLocaleLowerCase();
    return text.includes(name);
  }) ?? null;
}
