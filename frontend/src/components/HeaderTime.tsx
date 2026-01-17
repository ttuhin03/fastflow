import { useState, useEffect } from 'react'
import './HeaderTime.css'

export default function HeaderTime() {
    const [isUtc, setIsUtc] = useState(true)
    const [time, setTime] = useState(new Date())

    useEffect(() => {
        const timer = setInterval(() => {
            setTime(new Date())
        }, 1000)
        return () => clearInterval(timer)
    }, [])

    const formatTime = (date: Date, utc: boolean) => {
        return date.toLocaleTimeString('en-GB', {
            timeZone: utc ? 'UTC' : 'Europe/Berlin',
            hour12: false,
            hour: '2-digit',
            minute: '2-digit',
            second: '2-digit'
        })
    }

    return (
        <div className="header-time-container">
            <div className="header-time-content">
                <span className="header-time-clock">{formatTime(time, isUtc)}</span>
            </div>
            <button
                className={`header-time-toggle ${isUtc ? 'utc' : 'cet'}`}
                onClick={() => setIsUtc(!isUtc)}
                title="Switch Timezone"
            >
                {isUtc ? 'UTC' : 'CET'}
            </button>
        </div>
    )
}
