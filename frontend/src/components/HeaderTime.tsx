import { useState, useEffect, useCallback } from 'react'
import './HeaderTime.css'

const STORAGE_KEY_VARIANT = 'headerTimeVariant'
const STORAGE_KEY_UTC = 'headerTimeUtc'
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

function loadUtc(): boolean {
    try {
        const v = localStorage.getItem(STORAGE_KEY_UTC)
        if (v === 'true') return true
        if (v === 'false') return false
    } catch {
        /* localStorage unzugreifbar */
    }
    return true
}

export default function HeaderTime() {
    const [isUtc, setIsUtc] = useState(loadUtc)
    const [time, setTime] = useState(new Date())
    const [variant, setVariant] = useState<Variant>(() => loadVariant())

    useEffect(() => {
        const timer = setInterval(() => setTime(new Date()), 1000)
        return () => clearInterval(timer)
    }, [])

    const formatTime = useCallback((date: Date, utc: boolean) => {
        return date.toLocaleTimeString('en-GB', {
            timeZone: utc ? 'UTC' : 'Europe/Berlin',
            hour12: false,
            hour: '2-digit',
            minute: '2-digit',
            second: '2-digit',
        })
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

    const toggleUtc = useCallback(() => {
        setIsUtc((prev) => {
            const next = !prev
            try {
                localStorage.setItem(STORAGE_KEY_UTC, String(next))
            } catch {
                /* z. B. privater Modus */
            }
            return next
        })
    }, [])

    return (
        <div className="header-time-container">
            {variant === 'default' ? (
                <>
                    <div className="header-time-content">
                        <span className="header-time-clock">{formatTime(time, isUtc)}</span>
                    </div>
                    <button
                        className={`header-time-toggle ${isUtc ? 'utc' : 'cet'}`}
                        onClick={toggleUtc}
                        title="Zeitzone umschalten"
                    >
                        {isUtc ? 'UTC' : 'CET'}
                    </button>
                </>
            ) : (
                <div className="header-time-dual">
                    <span className="ht-dual-utc">{formatTime(time, true)} UTC</span>
                    <span className="ht-dual-sep">·</span>
                    <span className="ht-dual-cet">{formatTime(time, false)} CET</span>
                </div>
            )}
            <button
                type="button"
                className="header-time-cycle"
                onClick={cycleVariant}
                title={variant === 'default' ? 'Dual: beide Zeitzonen anzeigen' : 'Standard: eine Zeitzone mit Umschalter'}
                aria-label="Anzeige wechseln"
            >
                ◐
            </button>
        </div>
    )
}
