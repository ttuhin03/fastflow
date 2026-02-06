/**
 * Tests für Toast-Utilities (showSuccess, showError, showInfo, showWarning).
 * Mockt react-hot-toast.
 */

import { describe, it, expect, vi, beforeEach } from 'vitest'
import toast from 'react-hot-toast'
import { showSuccess, showError, showInfo, showWarning } from './toast'

vi.mock('react-hot-toast', () => ({
  default: Object.assign(vi.fn(), {
    success: vi.fn(),
    error: vi.fn(),
    dismiss: vi.fn(),
  }),
}))

describe('toast utils', () => {
  beforeEach(() => {
    vi.mocked(toast.success).mockClear()
    vi.mocked(toast.error).mockClear()
    vi.mocked(toast).mockClear()
  })

  it('showSuccess ruft toast.success mit der Nachricht auf', () => {
    showSuccess('Erfolg!')
    expect(toast.success).toHaveBeenCalledTimes(1)
    expect(toast.success).toHaveBeenCalledWith('Erfolg!')
  })

  it('showError ruft toast.error mit der Nachricht auf', () => {
    showError('Fehler!')
    expect(toast.error).toHaveBeenCalledTimes(1)
    expect(toast.error).toHaveBeenCalledWith('Fehler!')
  })

  it('showInfo ruft toast mit Icon auf', () => {
    showInfo('Info-Nachricht')
    expect(toast).toHaveBeenCalledTimes(1)
    expect(toast).toHaveBeenCalledWith('Info-Nachricht', {
      icon: 'ℹ️',
    })
  })

  it('showWarning ruft toast mit Icon auf', () => {
    showWarning('Warnung!')
    expect(toast).toHaveBeenCalledTimes(1)
    expect(toast).toHaveBeenCalledWith('Warnung!', {
      icon: '⚠️',
    })
  })
})
