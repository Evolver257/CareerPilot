import { expect, it } from "vitest";
import { shouldFollowMessages, splitAdvisorAnswer } from "./advisor-presentation";

it("leads with advice without discarding supporting evidence", () => {
  expect(splitAdvisorAnswer("## 统计\n61 个岗位\n## AI 建议（基于上述数据的推断）\n先学习 Python"))
    .toEqual({ answer: "先学习 Python", evidence: "## 统计\n61 个岗位" });
});
it("never hides an ordinary answer or unfinished advice", () => {
  for (const value of ["普通回答", "统计\n## AI 建议（基于上述数据的推断）\n"]) {
    expect(splitAdvisorAnswer(value)).toEqual({ answer: value, evidence: "" });
  }
});
it("only follows new output when the reader is near the bottom", () => {
  expect(shouldFollowMessages(100, 400, 1000)).toBe(false);
  expect(shouldFollowMessages(550, 400, 1000)).toBe(true);
});
