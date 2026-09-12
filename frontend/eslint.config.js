// Flat Config (ESLint 9+). ESLint 10 hat die eslintrc-Unterstützung ersatzlos
// entfernt — lib/config/ enthält nur noch die Flat-Variante —, weshalb die
// frühere .eslintrc.cjs schlicht nicht mehr gelesen wurde. Diese Datei ist die
// 1:1-Übersetzung davon: dieselben Regelsätze, derselbe Parser, dasselbe
// ignore-Muster.
import js from '@eslint/js'
import globals from 'globals'
import tseslint from '@typescript-eslint/eslint-plugin'
import reactHooks from 'eslint-plugin-react-hooks'
import reactRefresh from 'eslint-plugin-react-refresh'
import { defineConfig, globalIgnores } from 'eslint/config'

export default defineConfig([
  globalIgnores(['dist', 'coverage']),
  {
    // Entspricht dem früheren `--ext ts,tsx`; das Flag gibt es seit ESLint 9
    // nicht mehr, die Dateiauswahl gehört jetzt in die Config.
    files: ['**/*.{ts,tsx}'],
    extends: [
      js.configs.recommended,                 // war: eslint:recommended
      tseslint.configs['flat/recommended'],   // war: plugin:@typescript-eslint/recommended
      reactHooks.configs.flat.recommended,    // war: plugin:react-hooks/recommended
    ],
    languageOptions: {
      ecmaVersion: 2020,
      sourceType: 'module',
      globals: globals.browser,               // war: env.browser
    },
    plugins: { 'react-refresh': reactRefresh },
    rules: {
      'react-refresh/only-export-components': ['warn', { allowConstantExport: true }],
    },
  },
])
