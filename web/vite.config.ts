/// <reference types="vitest/config" />
import { defineConfig, type ProxyOptions } from 'vite';
import react from '@vitejs/plugin-react';

// Ohne @types/node: nur die Umgebungsvariablen werden gebraucht.
declare const process: { env: Record<string, string | undefined> };

const OUT_DIR = '../src/tapesmith/webui/static';

export default defineConfig(({ command, mode }) => {
  const isDevServer = command === 'serve' && mode !== 'test' && !process.env.VITEST;
  const target = process.env.P12_DEV_API;
  if (isDevServer && !target) {
    throw new Error(
      'P12_DEV_API fehlt: Port aus <TAPESMITH_HOME>\\web\\session.json lesen und z. B. P12_DEV_API=http://127.0.0.1:<port> setzen',
    );
  }
  // Origin auf genau das Ziel setzen, sonst lehnt der Dienst POSTs ab (CSRF-Prüfung).
  const proxyEntry: ProxyOptions | undefined = target
    ? {
        target,
        changeOrigin: true,
        configure: (proxy) => {
          const origin = new URL(target).origin;
          proxy.on('proxyReq', (proxyReq) => {
            proxyReq.setHeader('Origin', origin);
          });
        },
      }
    : undefined;

  return {
    plugins: [react()],
    base: '/',
    server: proxyEntry ? { proxy: { '/api': proxyEntry, '/health': proxyEntry } } : {},
    build: {
      outDir: OUT_DIR,
      emptyOutDir: true,
      assetsDir: 'assets',
      sourcemap: false,
      chunkSizeWarningLimit: 1500,
      rollupOptions: {
        output: {
          manualChunks(id: string) {
            if (id.includes('node_modules/@fluentui')) return 'fluent';
            if (id.includes('node_modules/konva') || id.includes('node_modules/react-konva')) return 'konva';
            return undefined;
          },
        },
      },
    },
    test: {
      environment: 'jsdom',
      globals: true,
      setupFiles: ['./vitest.setup.ts'],
      css: false,
      testTimeout: 20000,
      include: ['src/**/*.test.{ts,tsx}'],
      // Node 25 bringt ein eigenes localStorage mit (Warnung ohne Datei); jsdom stellt es für Tests bereit.
      execArgv: ['--no-experimental-webstorage'],
    },
  };
});
