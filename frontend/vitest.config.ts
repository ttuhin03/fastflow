/// <reference types="vitest" />
import path from 'node:path'
import { createRequire } from 'node:module'
import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// Je nach npm-Hoisting liegt React lokal (frontend/node_modules) oder im
// Workspace-Root — per require.resolve pinnen, damit nur eine Instanz läuft.
const require = createRequire(import.meta.url)
const resolvePkg = (pkg: string) => path.dirname(require.resolve(`${pkg}/package.json`))

export default defineConfig({
  plugins: [react()],
  resolve: {
    alias: {
      react: resolvePkg('react'),
      'react-dom': resolvePkg('react-dom'),
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
