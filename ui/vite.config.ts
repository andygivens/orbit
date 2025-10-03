import { defineConfig, loadEnv } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, process.cwd(), "");

  return {
    base: env.VITE_APP_BASE ?? "/ui/",
    plugins: [react()],
    server: {
      port: 5173,
      host: true
    },
    build: {
      outDir: "dist",
      emptyOutDir: true
    }
  };
});
