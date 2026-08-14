import { defineConfig, loadEnv } from "vite";

export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, ".", "");
  const apiPort = env.API_PORT || "8206";

  return {
    root: "frontend",
    envDir: "..",
    server: {
      host: "127.0.0.1",
      port: Number(env.VITE_PORT || 5206),
      strictPort: true,
      proxy: {
        "/api": {
          target: `http://127.0.0.1:${apiPort}`,
          changeOrigin: true,
        },
      },
    },
    preview: {
      host: "127.0.0.1",
      port: Number(env.PREVIEW_PORT || 6206),
      strictPort: true,
    },
    build: {
      outDir: "dist",
      emptyOutDir: true,
    },
  };
});
