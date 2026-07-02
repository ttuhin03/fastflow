import { useState, useMemo, useRef, useCallback } from 'react'
import { useTranslation } from 'react-i18next'
import { useNavigate } from 'react-router-dom'
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
  const navigate = useNavigate()
  const formatLocale = getFormatLocale()
  const [hoveredDay, setHoveredDay] = useState<string | null>(null)
  const tooltipRef = useRef<HTMLDivElement>(null)

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

  // Green-ramp heat level (0..4) for a day. Failures pull toward the "failed" tint.
  const getDayHeat = (day: DayData): number => {
    if (day.total_runs === 0) return 0
    // Days with significant failures render as a distinct "failed" cell.
    if (day.success_rate < 80 && day.failed_runs > day.successful_runs) return -1
    const runs = day.total_runs
    if (runs >= 10) return 4
    if (runs >= 5) return 3
    if (runs >= 2) return 2
    return 1
  }

  const getDayHeatClass = (day: DayData): string => {
    const heat = getDayHeat(day)
    return heat < 0 ? 'heat-fail' : `heat-${heat}`
  }

  const updateTooltipPosition = useCallback((e: React.MouseEvent<HTMLDivElement>) => {
    if (!tooltipRef.current) return
    const offset = 15
    const tooltipWidth = 250
    const tooltipHeight = 150
    let x = e.clientX + offset
    let y = e.clientY + offset
    if (x + tooltipWidth > window.innerWidth) x = e.clientX - tooltipWidth - offset
    if (y + tooltipHeight > window.innerHeight) y = e.clientY - tooltipHeight - offset
    tooltipRef.current.style.left = `${x + 10}px`
    tooltipRef.current.style.top = `${y + 10}px`
  }, [])

  const handleDayHover = (e: React.MouseEvent<HTMLDivElement>, dateStr: string) => {
    setHoveredDay(dateStr)
    updateTooltipPosition(e)
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
          <span className="legend-label">{t('calendar.less', 'Less')}</span>
          <div className="legend-colors">
            <div className="legend-color heat-0"></div>
            <div className="legend-color heat-1"></div>
            <div className="legend-color heat-2"></div>
            <div className="legend-color heat-3"></div>
            <div className="legend-color heat-4"></div>
          </div>
          <span className="legend-label">{t('calendar.more', 'More')}</span>
        </div>
      </div>
      
      <div className="calendar-grid">
        <div className="calendar-week-labels">
          <span>{t('calendar.mon', 'Mon')}</span>
          <span>{t('calendar.wed', 'Wed')}</span>
          <span>{t('calendar.fri', 'Fri')}</span>
        </div>
        
        <div className="calendar-weeks-container">
          <div className="calendar-month-labels">
            {monthLabels.map(({ weekIndex, month }) => {
              // Position based on week index (11px cell + 3px gap)
              const weekWidth = 11 + 3
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
                  
                  const isHovered = hoveredDay === day.dateStr

                  return (
                    <div
                      key={day.dateStr}
                      className={`calendar-day ${getDayHeatClass(day)} ${isHovered ? 'hovered' : ''}`}
                      onMouseEnter={(e) => handleDayHover(e, day.dateStr)}
                      onMouseMove={updateTooltipPosition}
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
          ref={tooltipRef}
          className="calendar-tooltip"
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
                      navigate(`/runs/${runId}`)
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
