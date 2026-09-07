import { describe, expect, it } from "vitest";
import { parseCampaignNumbers } from "./campaign-input";

describe("campaign numeric inputs", () => {
  it.each(["", "0", "201", "1.5", "NaN"])("rejects invalid job count %s", (value) => {
    expect(() => parseCampaignNumbers(value, "50")).toThrow("1–200");
  });
  it.each(["", "-1", "101", "Infinity"])("rejects invalid score %s", (value) => {
    expect(() => parseCampaignNumbers("200", value)).toThrow("0–100");
  });
  it("preserves the 200 boundary and fractional score", () => {
    expect(parseCampaignNumbers("200", "50.5")).toEqual({ max_jobs: 200, min_score: 50.5 });
  });
});
