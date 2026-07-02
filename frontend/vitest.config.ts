/// <reference types="vitest" />
import path from 'node:path'
import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

export default defineConfig({
  plugins: [react()],
  resolve: {
    // Im npm-Workspace liegt React 19 (docs) im Root und React 18 hier —
    // hart auf die lokale Kopie pinnen, damit nur eine React-Instanz läuft.
    alias: {
      react: path.resolve(__dirname, 'node_modules/react'),
      'react-dom': path.resolve(__dirname, 'node_modules/react-dom'),
      // CJS-Shim würde per nativem require das Root-React laden — Stub nutzt
      // das in React 18 eingebaute useSyncExternalStore (gleiche Instanz).
      'use-sync-external-store/shim': path.resolve(
        __dirname,
        'src/test/use-sync-external-store-shim.ts',
      ),
    },
  },
  test: {
    environment: 'jsdom',
    globals: true,
    include: ['src/**/*.{test,spec}.{ts,tsx}'],
    setupFiles: ['./src/test/setup.ts'],
    server: {
      deps: {
        // react-i18next ist im Workspace-Root gehoistet und würde extern (per
        // Node-Resolution) das Root-React 19 laden — inline verarbeiten, damit
        // der React-Alias greift. moduleDirectories, damit vitest das Paket im
        // Parent-node_modules überhaupt als Dependency erkennt.
        inline: [/react-i18next/],
        moduleDirectories: ['node_modules', '../node_modules'],
      },
    },
  },
})
