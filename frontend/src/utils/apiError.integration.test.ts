/**
 * Belegt, dass die Response-Interceptor-Kette aus api/client.ts einen
 * AxiosError unverändert durchreicht.
 *
 * Darauf steht die Fehlerauswertung an ~50 Aufrufstellen: utils/apiError
 * erkennt Fehler über axios.isAxiosError, also am Flag der AxiosError-Klasse.
 * Würde ein Interceptor den Fehler ersetzen oder in einen normalen Error
 * verpacken, fiele getErrorDetail still auf error.message zurück und in der UI
 * stünde überall "Request failed with status code 409" statt der Servermeldung.
 *
 * Der Fehler wird mit der echten AxiosError-Klasse erzeugt (ein eigener Adapter
 * muss selbst ablehnen — axios' validateStatus läuft dabei nicht); geprüft wird
 * hier die Kette danach, nicht die Fehlererzeugung in axios selbst.
 */

import { describe, it, expect, afterEach } from 'vitest'
import axios, { AxiosError, AxiosHeaders } from 'axios'
import type { InternalAxiosRequestConfig } from 'axios'
import apiClient from '../api/client'
import { getErrorDetail, getErrorStatus, getErrorCode } from './apiError'

const realAdapter = apiClient.defaults.adapter

// 409 statt 401: der 401-Zweig des Interceptors löst Redirect/Logout aus.
function failWith(status: number, data: unknown) {
  apiClient.defaults.adapter = async (config: InternalAxiosRequestConfig) => {
    const error = new AxiosError(
      `Request failed with status code ${status}`,
      'ERR_BAD_REQUEST',
      config,
    )
    error.response = {
      status,
      statusText: 'Error',
      data,
      headers: new AxiosHeaders(),
      config,
    }
    throw error
  }
}

async function captureError(url: string): Promise<unknown> {
  return apiClient.get(url).then(
    () => {
      throw new Error('Request hätte fehlschlagen müssen')
    },
    (e: unknown) => e,
  )
}

afterEach(() => {
  apiClient.defaults.adapter = realAdapter
})

describe('Fehler aus dem echten apiClient', () => {
  it('bleibt hinter den Interceptors ein AxiosError mit Server-detail', async () => {
    failWith(409, { detail: 'Pipeline läuft bereits' })

    const error = await captureError('/pipelines/demo/run')

    expect(axios.isAxiosError(error)).toBe(true)
    expect(getErrorStatus(error)).toBe(409)
    expect(getErrorDetail(error)).toBe('Pipeline läuft bereits')
  })

  it('trägt einen Objekt-detail mit error_code durch', async () => {
    failWith(409, { detail: { error_code: 'SESSION_EXPIRED' } })

    expect(getErrorCode(await captureError('/anything'))).toBe('SESSION_EXPIRED')
  })

  it('reicht eine 422-Validierungsliste als lesbaren Text durch', async () => {
    failWith(422, {
      detail: [{ loc: ['body', 'email'], msg: 'value is not a valid email address' }],
    })

    expect(getErrorDetail(await captureError('/users/invite')))
      .toBe('value is not a valid email address')
  })
})
