import { useMemo } from 'react'
import { LineChart, Line, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer, Legend } from 'recharts'
import './SuccessRateTrendChart.css'

interface DailyStat {
  date: string
  total_runs: number
  successful_runs: number
  failed_runs: number
  success_rate: number
}

interface SuccessRateTrendChartProps {
  dailyStats: DailyStat[]
  days?: number
}

export default function SuccessRateTrendChart({ dailyStats, days = 30 }: SuccessRateTrendChartProps) {
  // Bereite Daten für Chart vor (letzte N Tage)
  const chartData = useMemo(() => {
    const sortedStats = [...dailyStats].sort((a, b) => 
      new Date(a.date).getTime() - new Date(b.date).getTime()
    )
    
    // Neueste N Tage
    const recentStats = sortedStats.slice(-days)
    
    return recentStats.map(stat => ({
      date: new Date(stat.date).toLocaleDateString('de-DE', { month: 'short', day: 'numeric' }),
      dateFull: stat.date,
      successRate: parseFloat(stat.success_rate.toFixed(1)),
      totalRuns: stat.total_runs,
      successfulRuns: stat.successful_runs,
      failedRuns: stat.failed_runs
    }))
  }, [dailyStats, days])

  const CustomTooltip = ({ active, payload }: any) => {
    if (active && payload && payload.length) {
      const data = payload[0].payload
      return (
        <div className="success-rate-tooltip">
          <p className="tooltip-date">{data.dateFull}</p>
          <p className="tooltip-value">
            <span className="tooltip-label">Erfolgsrate:</span>
            <span className={`tooltip-number ${data.successRate >= 80 ? 'success' : data.successRate >= 50 ? 'warning' : 'error'}`}>
              {data.successRate}%
            </span>
          </p>
          <p className="tooltip-details">
            {data.successfulRuns} / {data.totalRuns} erfolgreich
          </p>
        </div>
      )
    }
    return null
  }

  if (chartData.length === 0) {
    return (
      <div className="no-chart-data">
        <p>Keine Daten für Trend-Analyse verfügbar</p>
      </div>
    )
  }

  return (
    <div className="success-rate-trend-chart">
      <h4>Erfolgsrate-Trend (letzte {days} Tage)</h4>
      <ResponsiveContainer width="100%" height={250}>
        <LineChart data={chartData} margin={{ top: 5, right: 20, left: 0, bottom: 5 }}>
          <CartesianGrid strokeDasharray="3 3" stroke="#444" />
          <XAxis 
            dataKey="date" 
            stroke="#888"
            style={{ fontSize: '12px' }}
            interval="preserveStartEnd"
          />
          <YAxis 
            domain={[0, 100]}
            stroke="#888"
            style={{ fontSize: '12px' }}
            label={{ value: 'Erfolgsrate (%)', angle: -90, position: 'insideLeft', style: { fill: '#888' } }}
          />
          <Tooltip content={<CustomTooltip />} />
          <Legend />
          <Line 
            type="monotone" 
            dataKey="successRate" 
            name="Erfolgsrate"
            stroke="#4caf50" 
            strokeWidth={2}
            dot={{ r: 3, fill: '#4caf50' }}
            activeDot={{ r: 5 }}
          />
        </LineChart>
      </ResponsiveContainer>
    </div>
  )
}
