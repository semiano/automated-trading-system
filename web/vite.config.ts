import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig({
  plugins: [react()],
  resolve: {
    // Prefer TypeScript sources when both .tsx/.ts and legacy .js files exist.
    extensions: [".tsx", ".ts", ".jsx", ".js", ".mjs", ".json"],
  },
  server: {
    port: 5173,
  },
});
