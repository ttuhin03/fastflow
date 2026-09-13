import type { ReactElement } from 'react'
import { chart, tooltipStyle } from '../styles/rechartsTheme'

/**
 * Custom tooltip — dark card, mono values, coloured series dots.
 * <Tooltip content={<FFTooltip unit="%" />} />
 */
export function FFTooltip(props: {
  active?: boolean
  payload?: Array<{ name: string; value: number | string; color: string }>
  label?: string | number
  unit?: string
}): ReactElement | null {
  const { active, payload, label, unit = '' } = props
  if (!active || !payload || !payload.length) return null
  return (
    <div style={tooltipStyle}>
      {label != null && (
        <div style={{ fontFamily: chart.fontMono, fontSize: 11, color: chart.axis, marginBottom: 6 }}>{label}</div>
      )}
      {payload.map((p, i) => (
        <div key={i} style={{ display: 'flex', alignItems: 'center', gap: 8, marginTop: i ? 4 : 0 }}>
          <span style={{ width: 8, height: 8, borderRadius: 2, background: p.color, flex: 'none' }} />
          <span style={{ flex: 1, color: chart.text, fontSize: 12, marginRight: 12 }}>{p.name}</span>
          <span style={{ fontFamily: chart.fontMono, fontWeight: 600, color: '#F4F4F5', fontSize: 12.5 }}>
            {p.value}{unit}
          </span>
        </div>
      ))}
    </div>
  )
}
