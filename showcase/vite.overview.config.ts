import { resolve } from "node:path";
import { defineConfig } from "vite";

export default defineConfig({
  build: {
    outDir: "dist-overview",
    // The production gateway serves this prefix locally; other paths go upstream.
    assetsDir: "candidates/overview-assets",
    rollupOptions: {
      input: {
        shell: resolve("candidates/sfo-overview.html"),
        overview: resolve("candidates/overview.html"),
      },
    },
  },
});
