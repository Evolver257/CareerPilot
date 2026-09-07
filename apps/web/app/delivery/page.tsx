"use client";

import { Suspense } from "react";
import { useSearchParams } from "next/navigation";
import AutomationWorkspace from "../../components/automation-workspace";

function DeliveryContent() {
  const campaignId = useSearchParams().get("campaign") ?? "";
  return <AutomationWorkspace key={campaignId} view="delivery" initialCampaignId={campaignId} />;
}

export default function DeliveryPage() {
  return <Suspense fallback={<p className="text-slate-500">正在加载投递计划…</p>}><DeliveryContent /></Suspense>;
}
