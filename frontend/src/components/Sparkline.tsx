import { useMemo } from 'react'
import './Sparkline.css'

interface SparklineProps {
  data: number[]
  width?: number
  height?: number
  color?: string
  showPoints?: boolean
}

export default function Sparkline({ 
  data, 
  width = 100, 
  height = 30, 
  color = '#4caf50',
  showPoints = false 
}: SparklineProps) {
  const path = useMemo(() => {
    if (data.length === 0) return ''
    
    const max = Math.max(...data)
    const min = Math.min(...data)
    const range = max - min || 1 // Vermeide Division durch 0
    
    const points = data.map((value, index) => {
      const x = (index / (data.length - 1 || 1)) * width
      const normalizedValue = (value - min) / range
      const y = height - (normalizedValue * height)
      return { x, y, value }
    })
    
    // Erstelle SVG-Pfad
    if (points.length === 0) return ''
    
    const pathData = points
      .map((point, index) => `${index === 0 ? 'M' : 'L'} ${point.x} ${point.y}`)
      .join(' ')
    
    return pathData
  }, [data, width, height])

  if (data.length === 0) {
    return (
      <div className="sparkline-empty" style={{ width, height }}>
        <span>-</span>
      </div>
    )
  }

  return (
    <svg 
      className="sparkline" 
      width={width} 
      height={height}
      viewBox={`0 0 ${width} ${height}`}
      preserveAspectRatio="none"
    >
      <defs>
        <linearGradient id="sparklineGradient" x1="0%" y1="0%" x2="0%" y2="100%">
          <stop offset="0%" stopColor={color} stopOpacity="0.3" />
          <stop offset="100%" stopColor={color} stopOpacity="0.05" />
        </linearGradient>
      </defs>
      
      {/* Füllung unter der Linie */}
      <path
        d={`${path} L ${width} ${height} L 0 ${height} Z`}
        fill="url(#sparklineGradient)"
      />
      
      {/* Hauptlinie */}
      <path
        d={path}
        fill="none"
        stroke={color}
        strokeWidth="1.5"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
      
      {/* Punkte */}
      {showPoints && data.length > 0 && (() => {
        const max = Math.max(...data)
        const min = Math.min(...data)
        const range = max - min || 1
        
        return data.map((value, index) => {
          const x = (index / (data.length - 1 || 1)) * width
          const normalizedValue = (value - min) / range
          const y = height - (normalizedValue * height)
          
          return (
            <circle
              key={index}
              cx={x}
              cy={y}
              r="2"
              fill={color}
            />
          )
        })
      })()}
    </svg>
  )
}
