import { useMemo } from 'react'
import { BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer, Legend } from 'recharts'
import './AverageRuntimeChart.css'

interface Run {
  id: string
  pipeline_name: string
  started_at: string
  finished_at: string | null
  status: string
}

interface AverageRuntimeChartProps {
  runs: Run[]
  days?: number
}

interface RuntimeData {
  date: string
  dateFull: string
  avgDuration: number
  minDuration: number
  maxDuration: number
  runCount: number
}

export default function AverageRuntimeChart({ runs, days = 30 }: AverageRuntimeChartProps) {
  const chartData = useMemo(() => {
    // Filtere nur erfolgreiche Runs mit finished_at
    const successfulRuns = runs.filter(
      run => run.status === 'SUCCESS' && run.finished_at
    )

    if (successfulRuns.length === 0) {
      return []
    }

    // Berechne Dauer für jeden Run
    const runsWithDuration = successfulRuns.map(run => {
      const start = new Date(run.started_at).getTime()
      const end = new Date(run.finished_at!).getTime()
      const durationMinutes = (end - start) / (1000 * 60) // Dauer in Minuten
      
      return {
        ...run,
        duration: durationMinutes,
        date: run.started_at.split('T')[0] // Datum als String
      }
    })

    // Gruppiere nach Datum
    const groupedByDate: Record<string, number[]> = {}
    runsWithDuration.forEach(run => {
      if (!groupedByDate[run.date]) {
        groupedByDate[run.date] = []
      }
      groupedByDate[run.date].push(run.duration)
    })

    // Berechne Statistiken pro Tag
    const stats: RuntimeData[] = Object.entries(groupedByDate)
      .map(([date, durations]) => {
        const sum = durations.reduce((a, b) => a + b, 0)
        const avg = sum / durations.length
        const min = Math.min(...durations)
        const max = Math.max(...durations)
        
        return {
          date: new Date(date).toLocaleDateString('de-DE', { month: 'short', day: 'numeric' }),
          dateFull: date,
          avgDuration: parseFloat(avg.toFixed(2)),
          minDuration: parseFloat(min.toFixed(2)),
          maxDuration: parseFloat(max.toFixed(2)),
          runCount: durations.length
        }
      })
      .sort((a, b) => new Date(a.dateFull).getTime() - new Date(b.dateFull).getTime())
      .slice(-days) // Letzte N Tage

    return stats
  }, [runs, days])

  const formatDuration = (minutes: number): string => {
    if (minutes < 1) {
      return `${Math.round(minutes * 60)}s`
    } else if (minutes < 60) {
      return `${Math.round(minutes)}m`
    } else {
      const hours = Math.floor(minutes / 60)
      const mins = Math.round(minutes % 60)
      return `${hours}h ${mins}m`
    }
  }

  const CustomTooltip = ({ active, payload }: any) => {
    if (active && payload && payload.length) {
      const data = payload[0].payload
      return (
        <div className="runtime-tooltip">
          <p className="tooltip-date">{data.dateFull}</p>
          <p className="tooltip-stat">
            <span className="tooltip-label">Durchschnitt:</span>
            <span className="tooltip-value">{formatDuration(data.avgDuration)}</span>
          </p>
          <p className="tooltip-stat">
            <span className="tooltip-label">Min:</span>
            <span className="tooltip-value">{formatDuration(data.minDuration)}</span>
          </p>
          <p className="tooltip-stat">
            <span className="tooltip-label">Max:</span>
            <span className="tooltip-value">{formatDuration(data.maxDuration)}</span>
          </p>
          <p className="tooltip-stat">
            <span className="tooltip-label">Runs:</span>
            <span className="tooltip-value">{data.runCount}</span>
          </p>
        </div>
      )
    }
    return null
  }

  if (chartData.length === 0) {
    return (
      <div className="no-chart-data">
        <p>Keine erfolgreichen Runs für Laufzeit-Analyse verfügbar</p>
      </div>
    )
  }

  return (
    <div className="average-runtime-chart">
      <h4>Durchschnittliche Laufzeit (letzte {days} Tage)</h4>
      <ResponsiveContainer width="100%" height={250}>
        <BarChart data={chartData} margin={{ top: 5, right: 20, left: 0, bottom: 5 }}>
          <CartesianGrid strokeDasharray="3 3" stroke="#444" />
          <XAxis 
            dataKey="date" 
            stroke="#888"
            style={{ fontSize: '12px' }}
            interval="preserveStartEnd"
          />
          <YAxis 
            stroke="#888"
            style={{ fontSize: '12px' }}
            label={{ value: 'Laufzeit (Minuten)', angle: -90, position: 'insideLeft', style: { fill: '#888' } }}
          />
          <Tooltip content={<CustomTooltip />} />
          <Legend />
          <Bar 
            dataKey="avgDuration" 
            name="Durchschnittliche Laufzeit"
            fill="#2196f3"
            radius={[4, 4, 0, 0]}
          />
        </BarChart>
      </ResponsiveContainer>
    </div>
  )
}
