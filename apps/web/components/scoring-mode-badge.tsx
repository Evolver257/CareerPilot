type LlmDeepScoreBadgeProps = {
  kind: "plan" | "report";
};

export function LlmDeepScoreBadge({ kind }: LlmDeepScoreBadgeProps) {
  const label = kind === "plan" ? "LLM 深评计划" : "LLM 深评报告";
  return (
    <span
      aria-label={label}
      className="llm-deep-score-badge"
      title="该内容使用 LLM 对高潜职位进行了深度匹配复核"
    >
      <svg aria-hidden="true" fill="none" height="14" viewBox="0 0 24 24" width="14">
        <path d="M12 3l1.35 4.15L17.5 8.5l-4.15 1.35L12 14l-1.35-4.15L6.5 8.5l4.15-1.35L12 3Z" fill="currentColor" />
        <path d="m18.5 14 .78 2.22 2.22.78-2.22.78L18.5 20l-.78-2.22L15.5 17l2.22-.78L18.5 14Z" fill="currentColor" opacity=".72" />
      </svg>
      {label}
    </span>
  );
}
