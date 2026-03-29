import { useMemo } from 'react'
import { useTranslation } from 'react-i18next'
import { LineChart, Line, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer, Legend } from 'recharts'
import { getFormatLocale } from '../utils/locale'
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
  const { t } = useTranslation()

  const chartData = useMemo(() => {
    const sortedStats = [...dailyStats].sort((a, b) =>
      new Date(a.date).getTime() - new Date(b.date).getTime()
    )

    const recentStats = sortedStats.slice(-days)

    return recentStats.map(stat => ({
      date: new Date(stat.date).toLocaleDateString(getFormatLocale(), { month: 'short', day: 'numeric' }),
      dateFull: stat.date,
      successRate: parseFloat(stat.success_rate.toFixed(1)),
      totalRuns: stat.total_runs,
      successfulRuns: stat.successful_runs,
      failedRuns: stat.failed_runs
    }))
  }, [dailyStats, days])

  const CustomTooltip = ({ active, payload }: { active?: boolean; payload?: Array<{ payload: {
    dateFull: string
    successRate: number
    successfulRuns: number
    totalRuns: number
  } }> }) => {
    if (active && payload && payload.length) {
      const data = payload[0].payload
      return (
        <div className="success-rate-tooltip">
          <p className="tooltip-date">{data.dateFull}</p>
          <p className="tooltip-value">
            <span className="tooltip-label">{t('charts.successRate.tooltipRate')}</span>
            <span className={`tooltip-number ${data.successRate >= 80 ? 'success' : data.successRate >= 50 ? 'warning' : 'error'}`}>
              {data.successRate}%
            </span>
          </p>
          <p className="tooltip-details">
            {t('charts.successRate.tooltipRuns', { successful: data.successfulRuns, total: data.totalRuns })}
          </p>
        </div>
      )
    }
    return null
  }

  if (chartData.length === 0) {
    return (
      <div className="no-chart-data">
        <p>{t('charts.successRate.empty')}</p>
      </div>
    )
  }

  return (
    <div className="success-rate-trend-chart">
      <h4>{t('charts.successRate.title', { days })}</h4>
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
            label={{ value: t('charts.successRate.yAxis'), angle: -90, position: 'insideLeft', style: { fill: '#888' } }}
          />
          <Tooltip content={<CustomTooltip />} />
          <Legend />
          <Line
            type="monotone"
            dataKey="successRate"
            name={t('charts.successRate.legend')}
            stroke="#22c55e"
            strokeWidth={2}
            dot={{ r: 3, fill: '#22c55e' }}
            activeDot={{ r: 5 }}
          />
        </LineChart>
      </ResponsiveContainer>
    </div>
  )
}
