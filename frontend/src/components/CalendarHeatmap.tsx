import { useState, useMemo } from 'react'
import { useTranslation } from 'react-i18next'
import { getFormatLocale } from '../utils/locale'
import './CalendarHeatmap.css'

interface DailyStat {
  date: string
  total_runs: number
  successful_runs: number
  failed_runs: number
  success_rate: number
  run_ids?: string[]  // Run-IDs für Tooltip
}

interface CalendarHeatmapProps {
  dailyStats: DailyStat[]
  days?: number
  /** Wenn false, wird die Überschrift „Laufhistorie“ nicht angezeigt (z. B. wenn die Seite bereits einen Sektionstitel hat). */
  showTitle?: boolean
}

interface DayData {
  date: Date
  dateStr: string
  total_runs: number
  successful_runs: number
  failed_runs: number
  success_rate: number
  run_ids?: string[]
}

export default function CalendarHeatmap({ dailyStats, days = 365, showTitle = true }: CalendarHeatmapProps) {
  const { t } = useTranslation()
  const formatLocale = getFormatLocale()
  const [hoveredDay, setHoveredDay] = useState<string | null>(null)
  const [tooltipPosition, setTooltipPosition] = useState({ x: 0, y: 0 })

  // Erstelle Map für schnellen Zugriff auf tägliche Statistiken
  const statsMap = useMemo(() => {
    const map = new Map<string, DailyStat>()
    dailyStats.forEach(stat => {
      map.set(stat.date, stat)
    })
    return map
  }, [dailyStats])

  // Generiere alle Tage für den gewählten Zeitraum
  // WICHTIG: Verwende UTC-Datum, um mit Backend-Daten (UTC) übereinzustimmen
  const allDays = useMemo(() => {
    const daysArray: DayData[] = []
    // Heute in UTC berechnen
    const now = new Date()
    const todayUTC = new Date(Date.UTC(now.getUTCFullYear(), now.getUTCMonth(), now.getUTCDate(), 0, 0, 0, 0))
    
    for (let i = days - 1; i >= 0; i--) {
      const date = new Date(todayUTC)
      date.setUTCDate(date.getUTCDate() - i)
      const dateStr = date.toISOString().split('T')[0]
      
      const stat = statsMap.get(dateStr)
      daysArray.push({
        date,
        dateStr,
        total_runs: stat?.total_runs || 0,
        successful_runs: stat?.successful_runs || 0,
        failed_runs: stat?.failed_runs || 0,
        success_rate: stat?.success_rate || 0,
        run_ids: stat?.run_ids || undefined
      })
    }
    
    return daysArray
  }, [days, statsMap])

  // Berechne Farbe für einen Tag
  const getDayColor = (day: DayData): string => {
    if (day.total_runs === 0) {
      return '#666' // Gray für keine Runs
    }
    
    // Grün wenn Erfolgsrate >= 80% oder keine Fehler
    if (day.success_rate >= 80 || day.failed_runs === 0) {
      // Intensität basierend auf Anzahl Runs
      const intensity = Math.min(day.total_runs / 10, 1) // Max 10 Runs = volle Intensität
      const lightness = 50 + (intensity * 30) // 50-80% lightness
      return `hsl(120, 60%, ${lightness}%)` // Grün
    }
    
    // Rot wenn Erfolgsrate < 80% oder mehr Fehler als Erfolge
    if (day.success_rate < 80 || day.failed_runs > day.successful_runs) {
      // Intensität basierend auf Fehlerrate
      const failureRatio = day.failed_runs / day.total_runs
      const intensity = Math.min(failureRatio * 2, 1) // Max bei 50% Fehlerrate
      const lightness = 50 + (intensity * 30)
      return `hsl(0, 70%, ${lightness}%)` // Rot
    }
    
    return '#666'
  }

  // Berechne CSS-Klasse für Intensität
  const getDayIntensity = (day: DayData): string => {
    if (day.total_runs === 0) return 'intensity-0'
    const runs = Math.min(day.total_runs, 10)
    return `intensity-${Math.floor(runs / 2)}`
  }

  const handleDayHover = (e: React.MouseEvent<HTMLDivElement>, dateStr: string) => {
    setHoveredDay(dateStr)
    // Position tooltip with offset, ensuring it doesn't go off-screen
    const offset = 15
    const tooltipWidth = 250 // Approximate tooltip width
    const tooltipHeight = 150 // Approximate tooltip height
    
    let x = e.clientX + offset
    let y = e.clientY + offset
    
    // Adjust if tooltip would go off right edge
    if (x + tooltipWidth > window.innerWidth) {
      x = e.clientX - tooltipWidth - offset
    }
    
    // Adjust if tooltip would go off bottom edge
    if (y + tooltipHeight > window.innerHeight) {
      y = e.clientY - tooltipHeight - offset
    }
    
    setTooltipPosition({ x, y })
  }

  const handleDayLeave = () => {
    setHoveredDay(null)
  }

  const hoveredDayData = hoveredDay ? allDays.find(d => d.dateStr === hoveredDay) : null

  // Gruppiere Tage in Wochen und identifiziere Monate
  const { weeks, monthLabels } = useMemo(() => {
    const weeksArray: DayData[][] = []
    const monthLabelsArray: { weekIndex: number; month: string }[] = []
    const monthSet = new Set<string>()
    let currentWeek: DayData[] = []
    let lastMonth = -1
    let weekIndex = 0
    
    allDays.forEach((day, index) => {
      const dayOfWeek = day.date.getDay()
      const currentMonth = day.date.getMonth()
      const dayOfMonth = day.date.getDate()
      
      // Erste Woche: Fülle mit leeren Tagen bis zum ersten Tag
      if (index === 0 && dayOfWeek !== 0) {
        for (let i = 0; i < dayOfWeek; i++) {
          currentWeek.push({
            date: new Date(0),
            dateStr: '',
            total_runs: 0,
            successful_runs: 0,
            failed_runs: 0,
            success_rate: 0
          })
        }
      }
      
      // Prüfe ob Monat gewechselt hat - zeige Label am ersten Tag des Monats oder am Montag nach Monatswechsel
      if (currentMonth !== lastMonth) {
        const monthKey = `${day.date.getFullYear()}-${currentMonth}`
        // Zeige Label wenn: erster Tag des Monats, oder Montag, oder erster Tag insgesamt
        if (dayOfMonth <= 7 || dayOfWeek === 1 || index === 0) {
          if (!monthSet.has(monthKey)) {
            const monthName = day.date.toLocaleDateString(formatLocale, { month: 'short' })
            monthLabelsArray.push({ weekIndex, month: monthName })
            monthSet.add(monthKey)
          }
        }
        lastMonth = currentMonth
      }
      
      currentWeek.push(day)
      
      // Wenn Sonntag oder letzter Tag, starte neue Woche
      if (dayOfWeek === 6 || index === allDays.length - 1) {
        weeksArray.push(currentWeek)
        currentWeek = []
        weekIndex++
      }
    })
    
    return { weeks: weeksArray, monthLabels: monthLabelsArray }
  }, [allDays])

  return (
    <div className="calendar-heatmap">
      <div className="calendar-heatmap-header">
        {showTitle && <h3>{t('dashboard.runHistory')}</h3>}
        <div className="calendar-legend">
          <span className="legend-label">Weniger</span>
          <div className="legend-colors">
            <div className="legend-color" style={{ backgroundColor: '#666' }}></div>
            <div className="legend-color" style={{ backgroundColor: 'hsl(120, 60%, 80%)' }}></div>
            <div className="legend-color" style={{ backgroundColor: 'hsl(120, 60%, 60%)' }}></div>
            <div className="legend-color" style={{ backgroundColor: 'hsl(120, 60%, 40%)' }}></div>
          </div>
          <span className="legend-label">Mehr</span>
        </div>
      </div>
      
      <div className="calendar-grid">
        <div className="calendar-week-labels">
          <span>Mo</span>
          <span>Mi</span>
          <span>Fr</span>
        </div>
        
        <div className="calendar-weeks-container">
          <div className="calendar-month-labels">
            {monthLabels.map(({ weekIndex, month }) => {
              // Berechne Position basierend auf Wochen-Index (11px Breite + 0.25rem gap)
              const weekWidth = 11 + 4 // 11px cell + 4px gap (0.25rem)
              const leftOffset = weekIndex * weekWidth
              
              return (
                <div
                  key={`${weekIndex}-${month}`}
                  className="calendar-month-label"
                  style={{ 
                    position: 'absolute',
                    left: `${leftOffset}px`
                  }}
                >
                  {month}
                </div>
              )
            })}
          </div>
          
          <div className="calendar-weeks">
            {weeks.map((week, weekIndex) => (
              <div key={weekIndex} className="calendar-week">
                {week.map((day, dayIndex) => {
                  if (day.dateStr === '') {
                    return <div key={dayIndex} className="calendar-day empty"></div>
                  }
                  
                  const color = getDayColor(day)
                  const isHovered = hoveredDay === day.dateStr
                  
                  return (
                    <div
                      key={day.dateStr}
                      className={`calendar-day ${getDayIntensity(day)} ${isHovered ? 'hovered' : ''}`}
                      style={{ backgroundColor: color }}
                      onMouseEnter={(e) => handleDayHover(e, day.dateStr)}
                      onMouseMove={(e) => {
                        const offset = 15
                        const tooltipWidth = 250
                        const tooltipHeight = 150
                        
                        let x = e.clientX + offset
                        let y = e.clientY + offset
                        
                        if (x + tooltipWidth > window.innerWidth) {
                          x = e.clientX - tooltipWidth - offset
                        }
                        
                        if (y + tooltipHeight > window.innerHeight) {
                          y = e.clientY - tooltipHeight - offset
                        }
                        
                        setTooltipPosition({ x, y })
                      }}
                      onMouseLeave={handleDayLeave}
                      aria-label={`${day.dateStr}: ${t('calendar.runsSuccessfulFailed', { total: day.total_runs, successful: day.successful_runs, failed: day.failed_runs })}`}
                    />
                  )
                })}
              </div>
            ))}
          </div>
        </div>
      </div>
      
      {hoveredDayData && hoveredDay && (
        <div
          className="calendar-tooltip"
          style={{
            left: `${tooltipPosition.x + 10}px`,
            top: `${tooltipPosition.y + 10}px`
          }}
        >
          <div className="tooltip-date">
            {new Date(hoveredDayData.dateStr).toLocaleDateString(formatLocale, {
              weekday: 'long',
              year: 'numeric',
              month: 'long',
              day: 'numeric'
            })}
          </div>
          <div className="tooltip-stats">
            <div className="tooltip-stat">
              <span className="tooltip-label">{t('calendar.totalRuns')}</span>
              <span className="tooltip-value">{hoveredDayData.total_runs}</span>
            </div>
            <div className="tooltip-stat">
              <span className="tooltip-label">{t('dashboard.successful')}:</span>
              <span className="tooltip-value success">{hoveredDayData.successful_runs}</span>
            </div>
            <div className="tooltip-stat">
              <span className="tooltip-label">{t('common.failed')}:</span>
              <span className="tooltip-value error">{hoveredDayData.failed_runs}</span>
            </div>
            <div className="tooltip-stat">
              <span className="tooltip-label">{t('calendar.successRate')}</span>
              <span className="tooltip-value">{hoveredDayData.success_rate.toFixed(1)}%</span>
            </div>
          </div>
          {hoveredDayData.run_ids && hoveredDayData.run_ids.length > 0 && (
            <div className="tooltip-run-ids">
              <div className="tooltip-run-ids-label">{t('calendar.runIds')}</div>
              <div className="tooltip-run-ids-list">
                {hoveredDayData.run_ids.map((runId) => (
                  <a
                    key={runId}
                    href={`/runs/${runId}`}
                    className="tooltip-run-id-link"
                    onClick={(e) => {
                      e.preventDefault()
                      window.location.href = `/runs/${runId}`
                    }}
                  >
                    {runId.substring(0, 8)}...
                  </a>
                ))}
                {hoveredDayData.total_runs > hoveredDayData.run_ids.length && (
                  <span className="tooltip-run-ids-more">
                    +{hoveredDayData.total_runs - hoveredDayData.run_ids.length} {t('common.more')}
                  </span>
                )}
              </div>
            </div>
          )}
        </div>
      )}
    </div>
  )
}
