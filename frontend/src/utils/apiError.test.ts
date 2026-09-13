import { describe, it, expect } from 'vitest'
import { AxiosError, AxiosHeaders } from 'axios'
import { getErrorDetail, getErrorStatus, getErrorCode } from './apiError'

function axiosErrorWith(status: number, data: unknown, message = 'Request failed'): AxiosError {
  const config = { headers: new AxiosHeaders() }
  const error = new AxiosError(message, 'ERR_BAD_REQUEST', config)
  error.response = { status, statusText: '', data, headers: {}, config }
  return error
}

describe('getErrorDetail', () => {
  it('nimmt den detail-String aus dem Antwortkörper', () => {
    expect(getErrorDetail(axiosErrorWith(403, { detail: 'Admin-Rechte erforderlich' })))
      .toBe('Admin-Rechte erforderlich')
  })

  it('fasst die msg-Felder einer 422-Validierungsliste zusammen', () => {
    // Regression: diese Liste wurde vorher direkt interpoliert und erschien
    // als "[object Object]".
    const error = axiosErrorWith(422, {
      detail: [
        { loc: ['body', 'email'], msg: 'value is not a valid email address', type: 'value_error' },
        { loc: ['body', 'role'], msg: 'unexpected value', type: 'value_error' },
      ],
    })
    expect(getErrorDetail(error)).toBe('value is not a valid email address; unexpected value')
  })

  it('fällt auf die Fehlermeldung zurück, wenn detail fehlt oder unbrauchbar ist', () => {
    expect(getErrorDetail(axiosErrorWith(500, {}, 'Network Error'))).toBe('Network Error')
    expect(getErrorDetail(axiosErrorWith(500, { detail: '  ' }, 'Network Error'))).toBe('Network Error')
    expect(getErrorDetail(axiosErrorWith(500, { detail: { code: 7 } }, 'Network Error'))).toBe('Network Error')
    expect(getErrorDetail(axiosErrorWith(422, { detail: [{ loc: ['body'] }] }, 'Network Error'))).toBe('Network Error')
  })

  it('kommt mit Nicht-Axios-Fehlern klar', () => {
    expect(getErrorDetail(new Error('kaputt'))).toBe('kaputt')
    expect(getErrorDetail(new Error(''))).toBe('')
    expect(getErrorDetail('irgendwas')).toBe('')
    expect(getErrorDetail(null)).toBe('')
    expect(getErrorDetail(undefined)).toBe('')
  })
})

describe('getErrorStatus', () => {
  it('liefert den HTTP-Status', () => {
    expect(getErrorStatus(axiosErrorWith(401, {}))).toBe(401)
    expect(getErrorStatus(axiosErrorWith(403, {}))).toBe(403)
  })

  it('liefert undefined ohne Antwort', () => {
    expect(getErrorStatus(new AxiosError('Network Error'))).toBeUndefined()
    expect(getErrorStatus(new Error('kaputt'))).toBeUndefined()
    expect(getErrorStatus(null)).toBeUndefined()
  })
})

describe('getErrorCode', () => {
  it('liest error_code aus einem Objekt-detail', () => {
    expect(getErrorCode(axiosErrorWith(401, { detail: { error_code: 'SESSION_EXPIRED' } })))
      .toBe('SESSION_EXPIRED')
  })

  it('liefert undefined wenn detail ein String, leer oder kein Fehlerobjekt ist', () => {
    expect(getErrorCode(axiosErrorWith(401, { detail: 'abgelaufen' }))).toBeUndefined()
    expect(getErrorCode(axiosErrorWith(401, { detail: { code: 1 } }))).toBeUndefined()
    expect(getErrorCode(axiosErrorWith(401, {}))).toBeUndefined()
    expect(getErrorCode(new Error('kaputt'))).toBeUndefined()
  })
})
