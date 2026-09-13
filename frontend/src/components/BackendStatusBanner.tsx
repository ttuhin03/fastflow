/**
 * Banner für gestörte Backend-Zustände.
 *
 * Existiert, weil ein DB-Ausfall bisher nirgends in der UI ankam: Die
 * WarningsBox wertet /api/settings/system-status aus, und der hängt über
 * get_current_user an der Datenbank – fällt die aus, liefert er 503 statt einer
 * Diagnose, und die Box rendert schlicht nichts. Dieses Banner zieht seinen
 * Zustand stattdessen aus /api/system/status (ohne Auth, ohne DB-Abhängigkeit
 * jenseits des Checks selbst) und aus dem Response-Interceptor.
 *
 * Bewusst nicht wegklickbar: Es beschreibt keinen Hinweis, sondern einen
 * Zustand, in dem die angezeigten Daten unvollständig oder veraltet sind.
 */
import { useEffect, useSyncExternalStore } from 'react'
import { useQuery } from '@tanstack/react-query'
import { useTranslation } from 'react-i18next'
import { LuCircleAlert, LuExternalLink } from 'react-icons/lu'
import apiClient from '../api/client'
import {
  clearDegraded,
  getDegradedState,
  reportDegraded,
  subscribeDegraded,
} from '../api/degradedState'
import './BackendStatusBanner.css'

interface SystemStatusResponse {
  status: 'ok' | 'degraded'
  failing: string[]
  detail?: string | null
  log_viewer_url?: string | null
  version?: string
}

/** Häufig genug, um im Incident nützlich zu sein; selten genug für ein Dauer-Polling. */
const POLL_INTERVAL_MS = 15_000

const LOG_VIEWER_URL_KEY = 'fastflow.logViewerUrl'

/**
 * Die Log-Viewer-URL kommt aus dem Backend – also aus genau der Quelle, die im
 * Störungsfall ausgefallen sein kann. Wer die Seite erst während der Störung
 * öffnet, bekäme sonst ein Banner ohne den Link, der gerade am meisten hilft.
 * Deshalb wird der zuletzt bekannte Wert lokal gemerkt.
 */
function readCachedLogViewerUrl(): string | null {
  try {
    return window.localStorage.getItem(LOG_VIEWER_URL_KEY)
  } catch {
    return null
  }
}

function cacheLogViewerUrl(url: string | null | undefined): void {
  try {
    if (url) window.localStorage.setItem(LOG_VIEWER_URL_KEY, url)
    else window.localStorage.removeItem(LOG_VIEWER_URL_KEY)
  } catch {
    // Privater Modus oder blockierter Storage: Der Link ist ein Komfort-Feature,
    // das Banner funktioniert auch ohne ihn.
  }
}

export default function BackendStatusBanner() {
  const { t } = useTranslation()
  const degraded = useSyncExternalStore(subscribeDegraded, getDegradedState, getDegradedState)

  const { data, isError } = useQuery<SystemStatusResponse>({
    queryKey: ['backend-status'],
    queryFn: async () => (await apiClient.get('/system/status')).data,
    refetchInterval: POLL_INTERVAL_MS,
    // Im Störungsfall ist genau diese Abfrage die einzige Informationsquelle –
    // sie darf nicht auf gecachte "alles gut"-Daten zurückfallen.
    staleTime: 0,
    retry: false,
  })

  useEffect(() => {
    if (isError) {
      reportDegraded({ reason: 'unreachable' })
      return
    }
    if (!data) return
    cacheLogViewerUrl(data.log_viewer_url)
    if (data.status === 'ok') {
      clearDegraded()
    } else if (data.failing?.includes('database')) {
      // Die request_id steht nur in der fehlgeschlagenen Antwort, die der
      // Interceptor gesehen hat - /api/system/status kennt sie nicht. Ohne das
      // Uebernehmen wuerde der naechste Poll sie mit undefined ueberschreiben
      // und damit nach spaetestens einem Intervall genau die Kennung loeschen,
      // mit der man den Vorfall im Log wiederfindet.
      const previous = getDegradedState()
      const carried = previous.reason === 'database' ? previous : undefined
      reportDegraded({
        reason: 'database',
        requestId: carried?.requestId,
        cause: data.detail ?? carried?.cause,
      })
    } else if (data.failing?.includes('sqlite_fallback')) {
      reportDegraded({ reason: 'sqlite_fallback' })
    }
  }, [data, isError])

  if (!degraded.reason) return null

  const logViewerUrl = data?.log_viewer_url || readCachedLogViewerUrl()
  const isFallback = degraded.reason === 'sqlite_fallback'

  return (
    <div
      className={`backend-status-banner${isFallback ? ' backend-status-banner--warning' : ''}`}
      role="alert"
      aria-live="assertive"
    >
      <LuCircleAlert className="backend-status-banner__icon" aria-hidden />
      <div className="backend-status-banner__body">
        <strong className="backend-status-banner__title">
          {t(`backendStatus.${degraded.reason}.title`)}
        </strong>
        <span className="backend-status-banner__text">
          {t(`backendStatus.${degraded.reason}.body`)}
        </span>
        {degraded.cause && (
          <code className="backend-status-banner__cause">{degraded.cause}</code>
        )}
        {degraded.requestId && (
          <span className="backend-status-banner__meta">
            {t('backendStatus.requestId')}{' '}
            <code className="backend-status-banner__request-id">{degraded.requestId}</code>
          </span>
        )}
      </div>
      {logViewerUrl && (
        <a
          className="backend-status-banner__link"
          href={logViewerUrl}
          target="_blank"
          rel="noreferrer noopener"
        >
          {t('backendStatus.openLogs')}
          <LuExternalLink aria-hidden />
        </a>
      )}
    </div>
  )
}
