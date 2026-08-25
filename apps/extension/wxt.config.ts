import { defineConfig } from "wxt";

export default defineConfig({
  manifest: {
    name: "CareerPilot Browser Agent",
    description: "Executes structured CareerPilot Browser Actions with human control.",
    permissions: ["activeTab", "tabs", "scripting"],
    host_permissions: ["http://localhost:3000/*", "http://localhost:8010/*"],
  },
});
