import { MarkdownContent } from "../markdown-content";

export function StreamingAnswer({ value }: { value: string }) {
  return <MarkdownContent className="mt-3" value={value} />;
}
