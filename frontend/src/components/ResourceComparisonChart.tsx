import { useMemo } from 'react'
import { useTranslation } from 'react-i18next'
import { LineChart, Line, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer, Legend } from 'recharts'
import './ResourceComparisonChart.css'

interface Metric {
  timestamp: string
  cpu_percent: number
  ram_mb: number
  ram_limit_mb?: number
}

interface Run {
  id: string
  pipeline_name: string
  started_at: string
  finished_at: string | null
}

interface ResourceComparisonChartProps {
  runs: Array<{
    run: Run
    metrics: Metric[]
  }>
  maxRuns?: number
}

export default function ResourceComparisonChart({ runs, maxRuns = 5 }: ResourceComparisonChartProps) {
  const { t } = useTranslation()

  const chartData = useMemo(() => {
    const recentRuns = runs
      .filter(r => r.metrics && r.metrics.length > 0)
      .slice(-maxRuns)
      .reverse()

    if (recentRuns.length === 0) {
      return []
    }

    const normalizedData: Array<{
      timePoint: number
      [key: string]: number | string
    }> = []

    recentRuns.forEach((runData, runIndex) => {
      const metrics = runData.metrics
      const runId = runData.run.id.substring(0, 8)
      const runLabel = `${runData.run.pipeline_name} (${runId})`

      metrics.forEach((metric, metricIndex) => {
        const timePoint = Math.round((metricIndex / (metrics.length - 1 || 1)) * 100)

        let dataPoint = normalizedData.find(dp => dp.timePoint === timePoint)
        if (!dataPoint) {
          dataPoint = { timePoint }
          normalizedData.push(dataPoint)
        }

        dataPoint[`cpu_${runIndex}`] = metric.cpu_percent
        dataPoint[`cpu_${runIndex}_label`] = runLabel

        dataPoint[`ram_${runIndex}`] = metric.ram_mb
      })
    })

    normalizedData.sort((a, b) => a.timePoint - b.timePoint)

    return normalizedData
  }, [runs, maxRuns])

  const recentSliceCount = chartData.length > 0 ? runs.slice(-maxRuns).length : 0

  const CustomTooltip = ({ active, payload }: { active?: boolean; payload?: Array<{ payload: Record<string, unknown>; dataKey: string }> }) => {
    if (active && payload && payload.length) {
      const data = payload[0].payload as { timePoint: number }
      return (
        <div className="resource-comparison-tooltip">
          <p className="tooltip-header">{t('charts.resourceComparison.tooltipRuntime', { pct: data.timePoint })}</p>
          {payload.map((entry, index: number) => {
            const key = entry.dataKey as string
            const isCpu = key.startsWith('cpu_')
            const value = entry.payload[key] as number
            const label = (entry.payload[`${key}_label`] as string) || key

            return (
              <p key={index} className="tooltip-stat">
                <span className="tooltip-label">{label}:</span>
                <span className="tooltip-value">
                  {isCpu ? `${value.toFixed(1)}%` : `${value.toFixed(0)} MB`}
                </span>
              </p>
            )
          })}
        </div>
      )
    }
    return null
  }

  if (chartData.length === 0) {
    return (
      <div className="no-chart-data">
        <p>{t('charts.resourceComparison.empty')}</p>
      </div>
    )
  }

  const colors = ['#22c55e', '#6366f1', '#f59e0b', '#818cf8', '#ef4444', '#38bdf8', '#fcd34d']

  return (
    <div className="resource-comparison-chart">
      <h4>{t('charts.resourceComparison.title', { count: recentSliceCount })}</h4>
      <div className="chart-tabs">
        <div className="chart-tab-content active">
          <h5>{t('charts.resourceComparison.cpuTab')}</h5>
          <ResponsiveContainer width="100%" height={250}>
            <LineChart data={chartData} margin={{ top: 5, right: 20, left: 0, bottom: 5 }}>
              <CartesianGrid strokeDasharray="3 3" stroke="#444" />
              <XAxis
                dataKey="timePoint"
                stroke="#888"
                style={{ fontSize: '12px' }}
                label={{ value: t('charts.resourceComparison.xAxisRuntime'), position: 'insideBottom', offset: -5, style: { fill: '#888' } }}
              />
              <YAxis
                domain={[0, 100]}
                stroke="#888"
                style={{ fontSize: '12px' }}
                label={{ value: t('charts.resourceComparison.yAxisCpu'), angle: -90, position: 'insideLeft', style: { fill: '#888' } }}
              />
              <Tooltip content={<CustomTooltip />} />
              <Legend />
              {runs.slice(-maxRuns).map((_, index) => {
                const color = colors[index % colors.length]
                const label = chartData[0]?.[`cpu_${index}_label`]
                const name = typeof label === 'string' ? label : t('charts.resourceComparison.runFallback', { index: index + 1 })
                return (
                  <Line
                    key={`cpu_${index}`}
                    type="monotone"
                    dataKey={`cpu_${index}`}
                    name={name}
                    stroke={color}
                    strokeWidth={2}
                    dot={false}
                    activeDot={{ r: 4 }}
                  />
                )
              })}
            </LineChart>
          </ResponsiveContainer>
        </div>
        <div className="chart-tab-content active">
          <h5>{t('charts.resourceComparison.ramTab')}</h5>
          <ResponsiveContainer width="100%" height={250}>
            <LineChart data={chartData} margin={{ top: 5, right: 20, left: 0, bottom: 5 }}>
              <CartesianGrid strokeDasharray="3 3" stroke="#444" />
              <XAxis
                dataKey="timePoint"
                stroke="#888"
                style={{ fontSize: '12px' }}
                label={{ value: t('charts.resourceComparison.xAxisRuntime'), position: 'insideBottom', offset: -5, style: { fill: '#888' } }}
              />
              <YAxis
                stroke="#888"
                style={{ fontSize: '12px' }}
                label={{ value: t('charts.resourceComparison.yAxisRam'), angle: -90, position: 'insideLeft', style: { fill: '#888' } }}
              />
              <Tooltip content={<CustomTooltip />} />
              <Legend />
              {runs.slice(-maxRuns).map((_, index) => {
                const color = colors[index % colors.length]
                const label = chartData[0]?.[`cpu_${index}_label`]
                const name = typeof label === 'string' ? label : t('charts.resourceComparison.runFallback', { index: index + 1 })
                return (
                  <Line
                    key={`ram_${index}`}
                    type="monotone"
                    dataKey={`ram_${index}`}
                    name={name}
                    stroke={color}
                    strokeWidth={2}
                    dot={false}
                    activeDot={{ r: 4 }}
                  />
                )
              })}
            </LineChart>
          </ResponsiveContainer>
        </div>
      </div>
    </div>
  )
}
