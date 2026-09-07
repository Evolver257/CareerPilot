import React from "react";
import { render, screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { MarkdownContent } from "./markdown-content";

describe("MarkdownContent", () => {
  it("renders ordered and nested lists with their original semantics", () => {
    render(
      <MarkdownContent
        value={"1. 准备基础\n   - Python\n   - Git\n2. 构建项目"}
      />,
    );

    const ordered = screen.getAllByRole("list").find((list) => list.tagName === "OL");
    expect(ordered).toBeDefined();
    expect(within(ordered!).getByText("准备基础")).toBeInTheDocument();
    expect(screen.getByText("Python").closest("ul")).toBeInTheDocument();
  });

  it("renders tables and fenced code blocks", () => {
    render(
      <MarkdownContent
        value={"| 技能 | 比例 |\n| --- | --- |\n| Python | 52% |\n\n```python\nprint('agent')\n```"}
      />,
    );

    expect(screen.getByRole("table")).toHaveTextContent("Python");
    expect(screen.getByText("print('agent')")).toHaveAttribute("data-language", "python");
  });

  it("renders fourth-level headings used by fallback career advice", () => {
    render(<MarkdownContent value="#### 能力分层" />);

    expect(screen.getByRole("heading", { name: "能力分层", level: 5 })).toBeInTheDocument();
  });
});
