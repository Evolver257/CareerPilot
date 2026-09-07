// Historical reports include a deterministic evidence preface before the actual advice.
// Preserve it, but let the user's answer lead the conversation.
export function splitAdvisorAnswer(content: string) {
  const marker = /^## AI 建议（基于上述数据的推断）\s*$/m;
  const match = marker.exec(content);
  if (!match) return { answer: content, evidence: "" };
  const answer = content.slice(match.index + match[0].length).trim();
  return answer
    ? { answer, evidence: content.slice(0, match.index).trim() }
    : { answer: content, evidence: "" };
}

export function shouldFollowMessages(scrollTop: number, height: number, total: number) {
  return total - scrollTop - height < 96;
}
