import { useState, useEffect, useCallback } from 'react'
import './HeaderTime.css'

const STORAGE_KEY = 'headerTimeVariant'
type Variant = 'default' | 'dual'

export default function HeaderTime() {
    const [isUtc, setIsUtc] = useState(true)
    const [time, setTime] = useState(new Date())
    const [variant, setVariant] = useState<Variant>(() =>
        (localStorage.getItem(STORAGE_KEY) as Variant) || 'default'
    )

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
        localStorage.setItem(STORAGE_KEY, next)
    }, [variant])

    return (
        <div className="header-time-container">
            {variant === 'default' ? (
                <>
                    <div className="header-time-content">
                        <span className="header-time-clock">{formatTime(time, isUtc)}</span>
                    </div>
                    <button
                        className={`header-time-toggle ${isUtc ? 'utc' : 'cet'}`}
                        onClick={() => setIsUtc(!isUtc)}
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
