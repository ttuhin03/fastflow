import { useState, useEffect, useRef, useId } from 'react'

export interface LineChartMetric {
  timestamp: string
  cpu_percent?: number
  ram_mb?: number
  ram_limit_mb?: number
  soft_limit_exceeded?: boolean
}

interface LineChartProps {
  data: LineChartMetric[]
  valueKey: 'cpu_percent' | 'ram_mb'
  maxValue: number
  color: string
  warningColor: string
  softLimit?: number
  hardLimit?: number
}

export function LineChart({ data, valueKey, maxValue, color, warningColor, softLimit, hardLimit }: LineChartProps) {
  const svgRef = useRef<SVGSVGElement>(null)
  const [dimensions, setDimensions] = useState({ width: 800, height: 200 })
  const gradientId = useId()

  useEffect(() => {
    const updateDimensions = () => {
      if (svgRef.current) {
        const container = svgRef.current.parentElement
        if (container) {
          setDimensions({
            width: container.clientWidth || 800,
            height: 200,
          })
        }
      }
    }
    updateDimensions()
    window.addEventListener('resize', updateDimensions)
    return () => window.removeEventListener('resize', updateDimensions)
  }, [])

  if (data.length === 0) {
    return <div className="no-chart-data">Keine Daten verfügbar</div>
  }

  const width = dimensions.width
  const height = dimensions.height
  const padding = { top: 20, right: 20, bottom: 30, left: 50 }
  const chartWidth = width - padding.left - padding.right
  const chartHeight = height - padding.top - padding.bottom

  const points = data.map((metric, index) => {
    const value = (metric[valueKey] ?? 0) as number
    const x = padding.left + (index / (data.length - 1 || 1)) * chartWidth
    const y = padding.top + chartHeight - (value / maxValue) * chartHeight
    return { x, y, value, metric, index }
  })

  const pathData = points
    .map((point, index) => `${index === 0 ? 'M' : 'L'} ${point.x} ${point.y}`)
    .join(' ')

  const areaPath = `${pathData} L ${points[points.length - 1].x} ${padding.top + chartHeight} L ${points[0].x} ${padding.top + chartHeight} Z`

  return (
    <div className="line-chart-container">
      <svg ref={svgRef} width={width} height={height} className="line-chart">
        <defs>
          <linearGradient id={`areaGradient-${gradientId}`} x1="0%" y1="0%" x2="0%" y2="100%">
            <stop offset="0%" stopColor={color} stopOpacity="0.3" />
            <stop offset="100%" stopColor={color} stopOpacity="0.05" />
          </linearGradient>
        </defs>

        {[0, 0.25, 0.5, 0.75, 1].map((ratio) => {
          const y = padding.top + chartHeight - ratio * chartHeight
          const value = ratio * maxValue
          return (
            <g key={ratio}>
              <line
                x1={padding.left}
                y1={y}
                x2={width - padding.right}
                y2={y}
                stroke="#444"
                strokeWidth="1"
                strokeDasharray="2,2"
              />
              <text
                x={padding.left - 10}
                y={y + 4}
                fill="#888"
                fontSize="10"
                textAnchor="end"
              >
                {valueKey === 'cpu_percent' ? `${value.toFixed(0)}%` : `${value.toFixed(0)}`}
              </text>
            </g>
          )
        })}

        <path d={areaPath} fill={`url(#areaGradient-${gradientId})`} />

        {hardLimit !== undefined && hardLimit > 0 && hardLimit <= maxValue && (
          <g>
            <line
              x1={padding.left}
              y1={padding.top + chartHeight - (hardLimit / maxValue) * chartHeight}
              x2={width - padding.right}
              y2={padding.top + chartHeight - (hardLimit / maxValue) * chartHeight}
              stroke="#f44336"
              strokeWidth="2"
              strokeDasharray="4,4"
              opacity="0.8"
            />
            <text
              x={width - padding.right + 5}
              y={padding.top + chartHeight - (hardLimit / maxValue) * chartHeight + 4}
              fill="#f44336"
              fontSize="10"
              fontWeight="600"
            >
              Hard Limit: {valueKey === 'cpu_percent' ? `${hardLimit.toFixed(0)}%` : `${hardLimit.toFixed(0)} MB`}
            </text>
          </g>
        )}

        {softLimit !== undefined && softLimit > 0 && softLimit <= maxValue && (
          <g>
            <line
              x1={padding.left}
              y1={padding.top + chartHeight - (softLimit / maxValue) * chartHeight}
              x2={width - padding.right}
              y2={padding.top + chartHeight - (softLimit / maxValue) * chartHeight}
              stroke="#ff9800"
              strokeWidth="2"
              strokeDasharray="3,3"
              opacity="0.8"
            />
            <text
              x={width - padding.right + 5}
              y={padding.top + chartHeight - (softLimit / maxValue) * chartHeight + 4}
              fill="#ff9800"
              fontSize="10"
              fontWeight="600"
            >
              Soft Limit: {valueKey === 'cpu_percent' ? `${softLimit.toFixed(0)}%` : `${softLimit.toFixed(0)} MB`}
            </text>
          </g>
        )}

        <path
          d={pathData}
          fill="none"
          stroke={color}
          strokeWidth="2"
          strokeLinecap="round"
          strokeLinejoin="round"
        />

        {points.map((point) => {
          const isWarning = point.metric.soft_limit_exceeded
          return (
            <g key={point.index}>
              <circle
                cx={point.x}
                cy={point.y}
                r={isWarning ? 5 : 3}
                fill={isWarning ? warningColor : color}
                stroke="#1a1a1a"
                strokeWidth="1"
              />
              <title>
                {new Date(point.metric.timestamp).toLocaleTimeString()}: {point.value.toFixed(1)}{valueKey === 'cpu_percent' ? '%' : ' MB'}
                {isWarning && ' (Soft-Limit überschritten)'}
              </title>
            </g>
          )
        })}

        {points.length > 1 && (
          <>
            {[0, Math.floor(points.length / 2), points.length - 1].map((idx) => {
              const point = points[idx]
              return (
                <text
                  key={idx}
                  x={point.x}
                  y={height - padding.bottom + 20}
                  fill="#888"
                  fontSize="10"
                  textAnchor="middle"
                >
                  {new Date(point.metric.timestamp).toLocaleTimeString()}
                </text>
              )
            })}
          </>
        )}
      </svg>
    </div>
  )
}
