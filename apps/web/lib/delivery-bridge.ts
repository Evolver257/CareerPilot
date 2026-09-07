export type DeliveryTask = { task_id: string; url: string; platform: "boss" | "zhaopin" };

export function launchDeliveryTasks(tasks: DeliveryTask[], timeoutMs = 10000): Promise<number> {
  const requestId = window.crypto.randomUUID();
  return new Promise((resolve, reject) => {
    const dispose = () => { clearTimeout(timer); window.removeEventListener("message", receive); };
    const receive = (event: MessageEvent) => {
      const data = event.data;
      if (event.source !== window || event.origin !== window.location.origin || data?.source !== "careerpilot-extension" || data.type !== "RECRUITMENT_TASK_BATCH_LAUNCH_RESULT" || data.request_id !== requestId) return;
      dispose();
      if (data.success === true && Number.isInteger(data.accepted_count) && data.accepted_count >= 0) resolve(data.accepted_count);
      else reject(new Error(data.error || "扩展未接受投递任务"));
    };
    const timer = setTimeout(() => {
      dispose();
      reject(new Error("未收到扩展确认。请重新加载最新扩展并刷新本页面；已创建的待启动任务会在重试时复用，请勿另建计划。"));
    }, timeoutMs);
    window.addEventListener("message", receive);
    window.postMessage({ source: "careerpilot-web", type: "RECRUITMENT_TASK_BATCH_LAUNCH_REQUEST", request_id: requestId, tasks }, window.location.origin);
  });
}
