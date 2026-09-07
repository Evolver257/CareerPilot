import { detectZhaopinPageState, isZhaopinPageUrl, zhaopinJobId } from "./zhaopin";
import type { ActionResultMessage, BrowserAction } from "../protocol";

function visible(element: HTMLElement): boolean {
  for (let node: HTMLElement | null = element; node; node = node.parentElement) {
    const style = getComputedStyle(node);
    if (style.display === "none" || style.visibility === "hidden" || node.hidden) return false;
  }
  return element.getBoundingClientRect().height > 0;
}
function label(element: HTMLElement): string { return (element.innerText || element.textContent || "").replace(/\s+/g, ""); }
function buttons(): HTMLElement[] {
  const root = document.querySelector(".summary-planes") || document;
  return [...root.querySelectorAll<HTMLElement>("button, a, [role='button'], .summary-planes__apply, .summary-planes__btn")].filter(visible)
    .filter((element) => !element.closest(".joblist-box__item, .job-card, .recommend-list, .recommend-job, .job-recommend"));
}
function confirmation(): "applied_button" | "success_notice" | null {
  if (buttons().some((element) => /^(已投递|已申请|已投递简历|已申请职位)$/.test(label(element)))) return "applied_button";
  // The live detail page pre-renders this modal hidden. Only visible confirmation counts.
  const delivered = [...document.querySelectorAll<HTMLElement>(".deliver-greeting-modal__title")].filter(visible);
  if (delivered.some((element) => label(element) === "已向对方发送简历和打招呼语")) return "success_notice";
  const notices = [...document.querySelectorAll<HTMLElement>("[role='alert'], [role='status'], [role='dialog'], .el-message, .ant-message, .toast, .apply-success")].filter(visible);
  return notices.some((element) => /^(简历)?投递成功[！!。]?|^申请成功[！!。]?/.test(label(element))) ? "success_notice" : null;
}
function blocked(): string | null {
  const state = detectZhaopinPageState();
  if (state !== "READY") return state;
  if ([...document.querySelectorAll<HTMLElement>(".summary-planes__invalid-text")].some(visible)) return "DOM_CHANGED";
  if ([...document.querySelectorAll<HTMLElement>("[role='dialog'], .el-dialog, .ant-modal, .resume-dialog, .apply-dialog")].filter(visible).length) return "UNKNOWN_STATE";
  return null;
}

export async function executeZhaopinApply(action: BrowserAction): Promise<ActionResultMessage> {
  const expected = action.metadata?.expected_job_id;
  const matches = () => isZhaopinPageUrl() && typeof expected === "string" && zhaopinJobId(window.location.href) === expected;
  const result = (success: boolean, status: string, state: string, proof?: string | null, error?: string): ActionResultMessage => ({
    type: "ACTION_RESULT", action_id: action.id, success, page_state: state, error,
    data: { platform: "zhaopin", page_url: window.location.href, zhaopin_action: action.action === "CLICK" ? "immediate_apply" : "inspect", application_status: status, confirmation: proof },
  });
  if (!matches()) return result(false, "wrong_job", "UNKNOWN_STATE", null, "不是本任务的智联岗位原页，已停止操作");
  // document_idle can precede SPA rendering. Wait for the detail surface, not a fixed blind click.
  for (let attempt = 0; attempt < 20 && detectZhaopinPageState() === "UNKNOWN_STATE"; attempt++) {
    await new Promise((resolve) => setTimeout(resolve, 250));
    if (!matches()) return result(false, "wrong_job", "UNKNOWN_STATE");
  }
  const proofBefore = confirmation();
  const state = blocked();
  if (state && !(state === "UNKNOWN_STATE" && proofBefore)) return result(false, "needs_user", state, null, "请处理登录、验证或简历确认窗口后继续");
  if (proofBefore) return result(true, "already_applied", "READY", proofBefore);
  if (action.action !== "CLICK") return result(true, "ready", "READY");
  const pendingKey = `careerpilot:zhaopin-apply-pending:${expected}`;
  try {
    if (window.sessionStorage.getItem(pendingKey)) return result(false, "uncertain", "UNKNOWN_STATE", null, "此前已点击投递但未确认结果，请人工核验；不会再次点击");
  } catch { return result(false, "storage_unavailable", "UNKNOWN_STATE", null, "无法保存投递防重复标记，请手动操作"); }
  const candidates = buttons().filter((element) => label(element) === "立即投递" && !element.matches(":disabled") && element.getAttribute("aria-disabled") !== "true" && !/(^|\s)(is-disabled|disabled)(\s|$)/.test(element.className));
  if (candidates.length !== 1) return result(false, "button_not_found", "DOM_CHANGED", null, "未找到唯一、可见且可用的立即投递按钮，请检查岗位是否有效");
  try { window.sessionStorage.setItem(pendingKey, action.id); }
  catch { return result(false, "storage_unavailable", "UNKNOWN_STATE", null, "无法保存投递防重复标记，请手动操作"); }
  candidates[0].scrollIntoView({ block: "center", behavior: "instant" });
  candidates[0].click();
  for (let attempt = 0; attempt < 40; attempt++) {
    await new Promise((resolve) => setTimeout(resolve, 250));
    if (!matches()) return result(false, "redirected", "UNKNOWN_STATE", null, "页面发生跳转，请人工核验投递结果");
    const proof = confirmation();
    const current = blocked();
    if (current && !(current === "UNKNOWN_STATE" && proof)) return result(false, "needs_user", current, null, "请处理页面验证或投递确认窗口，然后继续任务");
    if (proof) { window.sessionStorage.removeItem(pendingKey); return result(true, "submitted", "READY", proof); }
  }
  return result(false, "uncertain", "UNKNOWN_STATE", null, "已点击立即投递，但未检测到成功提示或已投递状态，请人工核验；不会重复点击");
}
