import { useMemo } from 'react'
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
  const chartData = useMemo(() => {
    // Neueste N Runs mit Metrics
    const recentRuns = runs
      .filter(r => r.metrics && r.metrics.length > 0)
      .slice(-maxRuns)
      .reverse() // Älteste zuerst für bessere Lesbarkeit

    if (recentRuns.length === 0) {
      return []
    }

    // Erstelle Datenpunkte für alle Runs (normalisiert auf Prozentsatz der Laufzeit)
    const normalizedData: Array<{
      timePoint: number // 0-100% der Laufzeit
      [key: string]: number | string // Dynamische Keys für jeden Run
    }> = []

    recentRuns.forEach((runData, runIndex) => {
      const metrics = runData.metrics
      const runId = runData.run.id.substring(0, 8)
      const runLabel = `${runData.run.pipeline_name} (${runId})`

      // Normalisiere auf 0-100% der Laufzeit
      metrics.forEach((metric, metricIndex) => {
        const timePoint = Math.round((metricIndex / (metrics.length - 1 || 1)) * 100)
        
        // Finde oder erstelle Datenpunkt
        let dataPoint = normalizedData.find(dp => dp.timePoint === timePoint)
        if (!dataPoint) {
          dataPoint = { timePoint }
          normalizedData.push(dataPoint)
        }

        // Füge CPU-Wert für diesen Run hinzu
        dataPoint[`cpu_${runIndex}`] = metric.cpu_percent
        dataPoint[`cpu_${runIndex}_label`] = runLabel

        // Füge RAM-Wert für diesen Run hinzu
        dataPoint[`ram_${runIndex}`] = metric.ram_mb
      })
    })

    // Sortiere nach timePoint
    normalizedData.sort((a, b) => a.timePoint - b.timePoint)

    return normalizedData
  }, [runs, maxRuns])

  const CustomTooltip = ({ active, payload }: any) => {
    if (active && payload && payload.length) {
      const data = payload[0].payload
      return (
        <div className="resource-comparison-tooltip">
          <p className="tooltip-header">Laufzeit: {data.timePoint}%</p>
          {payload.map((entry: any, index: number) => {
            const key = entry.dataKey
            const isCpu = key.startsWith('cpu_')
            const value = entry.value
            const label = data[`${key}_label`] || key

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
        <p>Keine Metrics für Resource-Vergleich verfügbar</p>
      </div>
    )
  }

  // Generiere Farben für Runs
  const colors = ['#4caf50', '#2196f3', '#ff9800', '#9c27b0', '#f44336', '#00bcd4', '#ffeb3b']

  return (
    <div className="resource-comparison-chart">
      <h4>Resource-Usage-Vergleich ({chartData.length > 0 ? runs.slice(-maxRuns).length : 0} Runs)</h4>
      <div className="chart-tabs">
        <div className="chart-tab-content active">
          <h5>CPU Usage (%)</h5>
          <ResponsiveContainer width="100%" height={250}>
            <LineChart data={chartData} margin={{ top: 5, right: 20, left: 0, bottom: 5 }}>
              <CartesianGrid strokeDasharray="3 3" stroke="#444" />
              <XAxis 
                dataKey="timePoint"
                stroke="#888"
                style={{ fontSize: '12px' }}
                label={{ value: 'Laufzeit (%)', position: 'insideBottom', offset: -5, style: { fill: '#888' } }}
              />
              <YAxis 
                domain={[0, 100]}
                stroke="#888"
                style={{ fontSize: '12px' }}
                label={{ value: 'CPU (%)', angle: -90, position: 'insideLeft', style: { fill: '#888' } }}
              />
              <Tooltip content={<CustomTooltip />} />
              <Legend />
              {runs.slice(-maxRuns).map((_, index) => {
                const color = colors[index % colors.length]
                const label = chartData[0]?.[`cpu_${index}_label`]
                const name = typeof label === 'string' ? label : `Run ${index + 1}`
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
          <h5>RAM Usage (MB)</h5>
          <ResponsiveContainer width="100%" height={250}>
            <LineChart data={chartData} margin={{ top: 5, right: 20, left: 0, bottom: 5 }}>
              <CartesianGrid strokeDasharray="3 3" stroke="#444" />
              <XAxis 
                dataKey="timePoint"
                stroke="#888"
                style={{ fontSize: '12px' }}
                label={{ value: 'Laufzeit (%)', position: 'insideBottom', offset: -5, style: { fill: '#888' } }}
              />
              <YAxis 
                stroke="#888"
                style={{ fontSize: '12px' }}
                label={{ value: 'RAM (MB)', angle: -90, position: 'insideLeft', style: { fill: '#888' } }}
              />
              <Tooltip content={<CustomTooltip />} />
              <Legend />
              {runs.slice(-maxRuns).map((_, index) => {
                const color = colors[index % colors.length]
                const label = chartData[0]?.[`cpu_${index}_label`]
                const name = typeof label === 'string' ? label : `Run ${index + 1}`
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
