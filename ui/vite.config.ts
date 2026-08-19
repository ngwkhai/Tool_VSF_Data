import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import tailwindcss from "@tailwindcss/vite";

export default defineConfig({
  plugins: [react(), tailwindcss()],
  server: {
    port: 5173,
    // Lúc phát triển, `npm run dev` phục vụ giao diện còn `vsf ui` phục vụ API.
    // Chuyển tiếp để không phải bật CORS chỉ vì một môi trường tạm.
    // SSE đi qua nguyên vẹn nhờ header `X-Accel-Buffering: no` mà API đã đặt —
    // không cần cấu hình thêm gì ở đây.
    proxy: {
      "/api": { target: "http://127.0.0.1:8000", changeOrigin: true },
    },
  },
  build: {
    outDir: "dist",
    emptyOutDir: true,
  },
});
