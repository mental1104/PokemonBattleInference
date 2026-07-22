import { defineConfig } from 'vite';
import vue from '@vitejs/plugin-vue';

/** Vite 开发与构建配置，开发期把 /v1 请求代理到 FastAPI。 */
export default defineConfig({
  plugins: [vue()],
  server: {
    port: 5173,
    proxy: {
      '/v1': {
        target: 'http://127.0.0.1:41104',
        changeOrigin: true,
      },
    },
  },
  test: {
    environment: 'jsdom',
  },
});
