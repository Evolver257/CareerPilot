import { isBossPageUrl } from "./platforms/boss";
import { isZhaopinPageUrl, zhaopinJobId } from "./platforms/zhaopin";

export function deliveryPlatform(value: string): "boss" | "zhaopin" | null {
  try {
    const url = new URL(value);
    if (url.protocol !== "https:" || url.username || url.password || (url.port && url.port !== "443")) return null;
    if (isBossPageUrl(value)) return "boss";
    if (isZhaopinPageUrl(value) && zhaopinJobId(value)) return "zhaopin";
  } catch { /* Invalid URL. */ }
  return null;
}
