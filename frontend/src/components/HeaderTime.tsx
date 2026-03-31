import { useState, useEffect, useCallback, useMemo } from 'react'
import { useTranslation } from 'react-i18next'
import { useUiPreferences } from '../contexts/UiPreferencesContext'
import './HeaderTime.css'

const STORAGE_KEY_VARIANT = 'headerTimeVariant'
const STORAGE_KEY_ACTIVE = 'headerTimeActiveIndex'
/** @deprecated nur für Migration wenn Paar noch UTC + Europe/Berlin */
const STORAGE_KEY_LEGACY_UTC = 'headerTimeUtc'

type Variant = 'default' | 'dual'

function loadVariant(): Variant {
    try {
        const v = localStorage.getItem(STORAGE_KEY_VARIANT)
        if (v === 'default' || v === 'dual') return v
    } catch {
        /* localStorage unzugreifbar (z. B. privater Modus) */
    }
    return 'default'
}

/**
 * Kurzname für die Umschalt-Anzeige (Button) und Dual-Modus (hinter der Uhrzeit).
 * - UTC: fest „UTC“ (kein Intl nötig).
 * - Sonst: Browser-Intl mit IANA-Zone; bevorzugt `shortGeneric` (z. B. CET/CEST, EST, JST),
 *   Fallback `short` (oft GMT+1 o. Ä.), dann letztes Segment des IANA-Namens.
 */
function shortTimezoneLabel(date: Date, timeZone: string): string {
    if (timeZone === 'UTC') return 'UTC'
    for (const style of ['shortGeneric', 'short'] as const) {
        try {
            const parts = new Intl.DateTimeFormat('en-GB', { timeZone, timeZoneName: style }).formatToParts(date)
            const name = parts.find((p) => p.type === 'timeZoneName')?.value
            if (name) return name
        } catch {
            /* nächster Stil oder Fallback unten */
        }
    }
    const tail = timeZone.split('/').pop()
    return tail || timeZone
}

function loadActiveIndex(tz1: string, tz2: string): 0 | 1 {
    try {
        const raw = localStorage.getItem(STORAGE_KEY_ACTIVE)
        if (raw === '0' || raw === '1') return Number(raw) as 0 | 1
        const legacy = localStorage.getItem(STORAGE_KEY_LEGACY_UTC)
        if (legacy === 'true' || legacy === 'false') {
            if (tz1 === 'UTC' && tz2 === 'Europe/Berlin') {
                return legacy === 'true' ? 0 : 1
            }
        }
    } catch {
        /* localStorage unzugreifbar */
    }
    return 0
}

export default function HeaderTime() {
    const { t } = useTranslation()
    const { headerTimezone1, headerTimezone2 } = useUiPreferences()
    const zones = useMemo(() => [headerTimezone1, headerTimezone2] as const, [headerTimezone1, headerTimezone2])

    const [activeIndex, setActiveIndex] = useState(() => loadActiveIndex(zones[0], zones[1]))
    const [time, setTime] = useState(new Date())
    const [variant, setVariant] = useState<Variant>(() => loadVariant())

    useEffect(() => {
        const timer = setInterval(() => setTime(new Date()), 1000)
        return () => clearInterval(timer)
    }, [])

    const formatTime = useCallback((date: Date, timeZone: string) => {
        try {
            return date.toLocaleTimeString('en-GB', {
                timeZone,
                hour12: false,
                hour: '2-digit',
                minute: '2-digit',
                second: '2-digit',
            })
        } catch {
            return date.toLocaleTimeString('en-GB', {
                timeZone: 'UTC',
                hour12: false,
                hour: '2-digit',
                minute: '2-digit',
                second: '2-digit',
            })
        }
    }, [])

    const cycleVariant = useCallback(() => {
        const next: Variant = variant === 'default' ? 'dual' : 'default'
        setVariant(next)
        try {
            localStorage.setItem(STORAGE_KEY_VARIANT, next)
        } catch {
            /* z. B. privater Modus, Speicher voll */
        }
    }, [variant])

    const toggleActive = useCallback(() => {
        setActiveIndex((prev) => {
            const next = (prev === 0 ? 1 : 0) as 0 | 1
            try {
                localStorage.setItem(STORAGE_KEY_ACTIVE, String(next))
            } catch {
                /* z. B. privater Modus */
            }
            return next
        })
    }, [])

    const tzA = zones[0]
    const tzB = zones[1]
    const activeTz = activeIndex === 0 ? tzA : tzB
    const labelA = shortTimezoneLabel(time, tzA)
    const labelB = shortTimezoneLabel(time, tzB)
    const activeShort = shortTimezoneLabel(time, activeTz)

    return (
        <div className="header-time-container">
            {variant === 'default' ? (
                <>
                    <div className="header-time-content">
                        <span className="header-time-clock">{formatTime(time, activeTz)}</span>
                    </div>
                    <button
                        type="button"
                        className={`header-time-toggle ${activeIndex === 0 ? 'tz-a' : 'tz-b'}`}
                        onClick={toggleActive}
                        title={t('headerTime.toggleTimezone')}
                    >
                        {activeShort}
                    </button>
                </>
            ) : (
                <div className="header-time-dual">
                    <span className="ht-dual-tz-a">
                        {formatTime(time, tzA)} {labelA}
                    </span>
                    <span className="ht-dual-sep">·</span>
                    <span className="ht-dual-tz-b">
                        {formatTime(time, tzB)} {labelB}
                    </span>
                </div>
            )}
            <button
                type="button"
                className="header-time-cycle"
                onClick={cycleVariant}
                title={variant === 'default' ? t('headerTime.showDual') : t('headerTime.showStandard')}
                aria-label={t('headerTime.switchDisplay')}
            >
                ◐
            </button>
        </div>
    )
}
