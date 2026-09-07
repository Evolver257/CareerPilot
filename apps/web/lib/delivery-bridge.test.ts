import { afterEach, expect, it, vi } from "vitest";
import { launchDeliveryTasks } from "./delivery-bridge";

afterEach(() => { vi.restoreAllMocks(); vi.useRealTimers(); });
it("waits for a correlated extension acknowledgement and ignores unrelated messages", async () => {
  const post = vi.spyOn(window, "postMessage").mockImplementation(() => {});
  const pending = launchDeliveryTasks([{ task_id: "one", url: "https://www.zhaopin.com/jobdetail/CC1.htm?task=one", platform: "zhaopin" }]);
  const request = post.mock.calls[0][0];
  const respond = (id: string, origin = window.location.origin) => window.dispatchEvent(new MessageEvent("message", {
    source: window, origin, data: { source: "careerpilot-extension", type: "RECRUITMENT_TASK_BATCH_LAUNCH_RESULT", request_id: id, success: true, accepted_count: 1 },
  }));
  respond("unrelated"); respond(request.request_id, "https://evil.example"); respond(request.request_id);
  await expect(pending).resolves.toBe(1);
});
it("times out instead of reporting a false launch success", async () => {
  vi.useFakeTimers(); vi.spyOn(window, "postMessage").mockImplementation(() => {});
  const assertion = expect(launchDeliveryTasks([], 25)).rejects.toThrow("未收到扩展确认");
  await vi.advanceTimersByTimeAsync(25); await assertion;
});
