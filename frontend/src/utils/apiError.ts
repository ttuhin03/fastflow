/**
 * Auswertung von Fehlern aus API-Aufrufen.
 *
 * Vorher las jede Fehlerbehandlung `error.response?.data?.detail || error.message`
 * über ein `any` direkt aus dem Fehlerobjekt. Das war an ~50 Stellen dupliziert,
 * hat den Typ verloren und bei Validierungsfehlern die falsche Ausgabe erzeugt
 * (siehe getErrorDetail).
 */

import axios from 'axios'

/** Fehlerkörper von FastAPI. `detail` ist ein String — bei 422 eine Liste. */
interface ApiErrorBody {
  detail?: unknown
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null
}

/**
 * Lesbarer Detailtext eines API-Fehlers.
 *
 * FastAPI legt die Begründung in `detail`. Bei Validierungsfehlern (422) ist das
 * aber eine Liste aus `{loc, msg, type}`: die landete bisher als "[object Object]"
 * in der Meldung, weil überall direkt auf `detail` zugegriffen wurde. Solche
 * Listen werden hier zu ihren `msg`-Feldern zusammengefasst.
 *
 * Liefert '' wenn nichts Brauchbares dasteht — Aufrufer hängen ihren eigenen
 * Fallback mit `|| t('...')` an.
 */
export function getErrorDetail(error: unknown): string {
  if (axios.isAxiosError<ApiErrorBody>(error)) {
    const detail = error.response?.data?.detail
    if (typeof detail === 'string' && detail.trim()) return detail
    if (Array.isArray(detail)) {
      const messages = detail
        .map((issue) => (isRecord(issue) && typeof issue.msg === 'string' ? issue.msg : null))
        .filter((msg): msg is string => msg !== null && msg.trim() !== '')
      if (messages.length) return messages.join('; ')
    }
  }
  if (error instanceof Error && error.message) return error.message
  return ''
}

/** HTTP-Status eines API-Fehlers, oder undefined wenn die Anfrage nie ankam. */
export function getErrorStatus(error: unknown): number | undefined {
  return axios.isAxiosError(error) ? error.response?.status : undefined
}

/**
 * Maschinenlesbarer Fehlercode, falls der Server statt eines Texts ein Objekt
 * in `detail` liefert — der Refresh-Endpoint macht das mit `error_code`.
 */
export function getErrorCode(error: unknown): string | undefined {
  if (!axios.isAxiosError<ApiErrorBody>(error)) return undefined
  const detail = error.response?.data?.detail
  if (!isRecord(detail)) return undefined
  return typeof detail.error_code === 'string' ? detail.error_code : undefined
}
