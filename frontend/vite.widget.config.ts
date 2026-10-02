// Builds the embeddable widget as one script a payer drops into any page:
//   <script src="https://<host>/widget/payer-assistant.js"></script>
//   <script>PayerAssistant.mount({ apiBase, getPortalToken })</script>
import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import path from "node:path";

export default defineConfig({
  plugins: [react()],
  resolve: { alias: { "@": path.resolve(__dirname, "src") } },
  define: { "process.env.NODE_ENV": JSON.stringify("production") },
  build: {
    outDir: "dist/widget",
    emptyOutDir: false,
    cssCodeSplit: false,
    lib: {
      entry: path.resolve(__dirname, "src/widget/embed.tsx"),
      name: "PayerAssistant",
      formats: ["iife"],
      fileName: () => "payer-assistant.js",
    },
  },
});
