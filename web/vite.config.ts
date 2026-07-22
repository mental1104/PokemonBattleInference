import { defineConfig } from 'vite';
import vue from '@vitejs/plugin-vue';

/** Vite 开发与构建配置，开发期把同源 /api 请求代理到 FastAPI。 */
export default defineConfig({
  plugins: [vue()],
  server: {
    port: 5173,
    proxy: {
      '/api': {
        target: 'http://127.0.0.1:41104',
        changeOrigin: true,
        rewrite: (path) => path.replace(/^\/api/, ''),
      },
    },
  },
  test: {
    environment: 'jsdom',
  },
});
