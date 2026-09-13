import { readFileSync } from "node:fs";
import { join } from "node:path";

import { NextResponse } from "next/server";

export const dynamic = "force-dynamic";

function buildId() {
  if (process.env.NEXT_PUBLIC_APP_VERSION) return process.env.NEXT_PUBLIC_APP_VERSION;
  try {
    return readFileSync(join(process.cwd(), ".next", "BUILD_ID"), "utf8").trim() || "dev";
  } catch {
    return "dev";
  }
}

export function GET() {
  return NextResponse.json({
    version: buildId(),
    build_time: process.env.NEXT_PUBLIC_BUILD_TIME || null,
  });
}
