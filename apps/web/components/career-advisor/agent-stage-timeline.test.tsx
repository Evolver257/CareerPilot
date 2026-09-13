import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import {
  createAgentRun,
  eventFromCareerAdvisor,
  reduceAgentRun,
} from "./agent-event-adapter";
import { AgentStageTimeline } from "./agent-stage-timeline";

describe("AgentStageTimeline", () => {
  it("reveals a stage only after its event occurs", () => {
    let run = createAgentRun("message-1");
    const view = render(<AgentStageTimeline run={run} />);

    expect(screen.getByText("理解问题")).toBeInTheDocument();
    expect(screen.queryByText("制定分析步骤")).not.toBeInTheDocument();
    expect(screen.queryByText("组织职业建议")).not.toBeInTheDocument();

    run = reduceAgentRun(
      run,
      eventFromCareerAdvisor(
        "intent_detected",
        { message_id: "message-1", event_id: "planning-1" },
        "message-1",
        1,
      ),
    );
    view.rerender(<AgentStageTimeline run={run} />);

    expect(screen.getByText("理解问题")).toBeInTheDocument();
    expect(screen.getByText("制定分析步骤")).toBeInTheDocument();
    expect(screen.queryByText("检索岗位知识库")).not.toBeInTheDocument();
  });
});
