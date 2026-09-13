import { describe, expect, it } from "vitest";

import {
  agentRunFromMessage,
  createAgentRun,
  eventFromCareerAdvisor,
  reduceAgentRun,
} from "./agent-event-adapter";
import type { CareerAdvisorMessage } from "../../lib/api";

function apply(run: ReturnType<typeof createAgentRun>, type: string, payload: Record<string, unknown>, sequence: number) {
  return reduceAgentRun(run, eventFromCareerAdvisor(type, payload, run.runId, sequence));
}

describe("agent event adapter", () => {
  it("maps real career-advisor events to a user-facing stage timeline", () => {
    let run = createAgentRun("message-1");
    expect(run.stageHistory).toEqual(["understanding"]);
    run = apply(run, "message_started", { message_id: "message-1", event_id: "e1" }, 1);
    run = apply(run, "intent_detected", { message_id: "message-1", planned_tools: ["search_job_knowledge"], event_id: "e2" }, 2);
    expect(run.stageHistory).toEqual(["understanding", "planning"]);
    run = apply(run, "retrieval_status", { message_id: "message-1", stage: "retrieval", label: "正在检索岗位", event_id: "e3" }, 3);
    run = apply(run, "tool_finished", { message_id: "message-1", tool: "search_job_knowledge", output: { sample_count: 12, citation_count: 6 }, event_id: "e4" }, 4);
    run = apply(run, "delta", { message_id: "message-1", content: "# 建议", event_id: "e5" }, 5);

    expect(run.stage).toBe("writing");
    expect(run.status).toBe("running");
    expect(run.plannedTools).toEqual(["search_job_knowledge"]);
    expect(run.tools[0]?.displayName).toBe("检索岗位知识库");
    expect(run.tools[0]?.resultSummary).toContain("12");
    expect(run.answerStarted).toBe(true);
    expect(run.stageHistory).toEqual(["understanding", "planning", "searching", "writing"]);
    expect(run.stageHistory).not.toContain("finalizing");
  });

  it("deduplicates an event when a reconnect replays the same event id", () => {
    let run = createAgentRun("message-1");
    run = apply(run, "tool_finished", { tool: "search_jobs", event_id: "same-event", output: { count: 3 } }, 1);
    const replay = eventFromCareerAdvisor("tool_finished", { tool: "search_jobs", event_id: "same-event", output: { count: 3 } }, "message-1", 99);
    const next = reduceAgentRun(run, replay);
    expect(next).toBe(run);
    expect(next.tools).toHaveLength(1);
  });

  it("keeps terminal state and never exposes internal reasoning text", () => {
    let run = createAgentRun("message-1");
    run = apply(run, "message_completed", { message_id: "message-1", event_id: "e1" }, 1);
    expect(run.status).toBe("completed");
    expect(run.stage).toBe("completed");
    expect(run.label).toBe("已完成");
    expect(run.detail).not.toMatch(/thought|chain of thought|推理过程/i);
  });

  it("counts only executed business tools and uses persisted latency", () => {
    const message = {
      id: "message-1",
      session_id: "session-1",
      role: "assistant",
      content: "已完成",
      status: "COMPLETED",
      intent: null,
      model_provider: "openai",
      model_name: "test",
      token_usage: {},
      answer_metadata: { sample_count: 46, citation_count: 8 },
      latency_ms: 23967.3,
      error_message: null,
      created_at: "2026-09-11T00:00:00.000Z",
      updated_at: "2026-09-11T00:00:01.000Z",
      citations: [],
      tool_trace: [
        { tool: "react_native_decision", output: {} },
        {
          tool: "analyze_resume_gap",
          output: { sample_count: 46, evidence_count: 3 },
          governance: { execution: { execution_status: "SUCCESS", latency_ms: 900 } },
        },
        { tool: "llamaindex_react_workflow", output: {} },
      ],
    } as CareerAdvisorMessage;

    const run = agentRunFromMessage(message);
    expect(run.tools.map((item) => item.tool)).toEqual(["analyze_resume_gap"]);
    expect(run.latencyMs).toBe(23967.3);
  });
});
