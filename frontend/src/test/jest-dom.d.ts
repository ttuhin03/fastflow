// Typ-Augmentation für die in setup.ts via expect.extend registrierten
// jest-dom-Matcher (Pendant zu @testing-library/jest-dom/types/vitest.d.ts,
// das wegen des Workspace-Hoistings nicht direkt importiert werden kann).
import { type expect } from 'vitest'
import { type TestingLibraryMatchers } from '@testing-library/jest-dom/matchers'

declare module 'vitest' {
  // `T = any` muss die Signatur aus @vitest/expect spiegeln (Assertion<T = any>):
  // Interface-Merging verlangt identische Typparameter, `unknown` bricht es.
  // Das leere Interface ist bei einer Augmentation ebenfalls der Zweck.
  /* eslint-disable @typescript-eslint/no-explicit-any, @typescript-eslint/no-empty-object-type */
  interface Assertion<T = any> extends TestingLibraryMatchers<typeof expect.stringContaining, T> {}
  interface AsymmetricMatchersContaining
    extends TestingLibraryMatchers<typeof expect.stringContaining, unknown> {}
  /* eslint-enable @typescript-eslint/no-explicit-any, @typescript-eslint/no-empty-object-type */
}
