import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import tailwindcss from "@tailwindcss/vite";

export default defineConfig({
  plugins: [react(), tailwindcss()],
  server: {
    port: 5173,
    proxy: {
      "/api": { target: "http://localhost:8000", changeOrigin: true },
    },
  },
  build: {
    outDir: "dist",
    sourcemap: false,
    chunkSizeWarningLimit: 400, // vendor (react-dom + framer-motion) is ~375 kB; the entry chunk stays well under 250 kB
    rollupOptions: {
      output: {
        // Long-lived vendor chunk (react + framer-motion) separate from app code; the syntax highlighter and the
        // drawers are split further via React.lazy.
        manualChunks(id: string) {
          if (!id.includes("node_modules")) return undefined;
          if (/[\\/]node_modules[\\/](react|react-dom|scheduler)[\\/]/.test(id)) return "vendor";
          if (/[\\/]node_modules[\\/](framer-motion|motion-dom|motion-utils)[\\/]/.test(id)) return "vendor";
          return undefined;
        },
      },
    },
  },
});
