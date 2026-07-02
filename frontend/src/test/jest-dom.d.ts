// Typ-Augmentation für die in setup.ts via expect.extend registrierten
// jest-dom-Matcher (Pendant zu @testing-library/jest-dom/types/vitest.d.ts,
// das wegen des Workspace-Hoistings nicht direkt importiert werden kann).
import 'vitest'
import { type TestingLibraryMatchers } from '@testing-library/jest-dom/matchers'

declare module 'vitest' {
  interface Assertion<T = any> extends TestingLibraryMatchers<any, T> {}
  interface AsymmetricMatchersContaining extends TestingLibraryMatchers<any, any> {}
}
