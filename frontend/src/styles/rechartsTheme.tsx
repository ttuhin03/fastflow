/* ============================================================================
   FastFlow · Recharts theme  (rechartsTheme.tsx)
   Reads CSS custom properties at runtime to stay in sync with variables.css.

   Usage:
     import { chart, FFTooltip, axisProps, gridProps } from '../styles/rechartsTheme'

     <ResponsiveContainer width="100%" height={160}>
       <AreaChart data={data} margin={{ top: 8, right: 8, bottom: 0, left: -16 }}>
         <defs>
           <linearGradient id="fill1" x1="0" y1="0" x2="0" y2="1">
             <stop offset="0%"  stopColor={chart.c1} stopOpacity={0.18} />
             <stop offset="100%" stopColor={chart.c1} stopOpacity={0} />
           </linearGradient>
         </defs>
         <CartesianGrid {...gridProps} />
         <XAxis dataKey="t" {...axisProps} />
         <YAxis {...axisProps} domain={[0, 100]} />
         <Tooltip content={<FFTooltip unit="%" />} cursor={{ stroke: chart.grid }} />
         <Area type="monotone" dataKey="cpu" stroke={chart.c1} strokeWidth={2.5}
               fill="url(#fill1)" dot={false} activeDot={{ r: 3, fill: chart.c1 }} />
       </AreaChart>
     </ResponsiveContainer>
   ========================================================================== */

import type { CSSProperties, ReactElement, SVGProps } from 'react'

const cssVar = (name: string, fallback: string): string => {
  if (typeof window === 'undefined') return fallback
  const v = getComputedStyle(document.documentElement).getPropertyValue(name).trim()
  return v || fallback
}

/** Palette + line colours, resolved from CSS variables. */
export const chart = {
  c1: cssVar('--chart-1', '#6E62F5'),
  c2: cssVar('--chart-2', '#3ECF8E'),
  c3: cssVar('--chart-3', '#4D9CF7'),
  c4: cssVar('--chart-4', '#F5A623'),
  c5: cssVar('--chart-5', '#C77DFF'),
  grid: cssVar('--chart-grid', '#1E1E24'),
  axis: cssVar('--chart-axis', '#52525B'),
  text: cssVar('--color-text-secondary', '#A0A0AB'),
  surface: cssVar('--color-surface-4', '#26262D'),
  border: cssVar('--color-border-light', '#2A2A32'),
  fontMono: cssVar('--font-mono', 'JetBrains Mono, monospace'),
  fontUi: cssVar('--font-family', 'Geist, sans-serif'),
}

/** Ordered series colours for multi-series charts. */
export const series = [chart.c1, chart.c2, chart.c3, chart.c4, chart.c5]

/** Spread onto <XAxis>/<YAxis>. Thin, quiet, mono tick labels. */
export const axisProps = {
  stroke: chart.axis,
  tick: { fill: chart.text, fontSize: 11, fontFamily: chart.fontMono } as SVGProps<SVGTextElement>,
  tickLine: false,
  axisLine: { stroke: chart.grid },
  tickMargin: 8,
} as const

/** Spread onto <CartesianGrid>. Horizontal hairlines only. */
export const gridProps = {
  stroke: chart.grid,
  strokeDasharray: '0',
  vertical: false,
} as const

/** Container tooltip style (if you don't use the custom component below). */
export const tooltipStyle: CSSProperties = {
  background: chart.surface,
  border: `1px solid ${chart.border}`,
  borderRadius: 8,
  boxShadow: '0 4px 12px rgba(0,0,0,0.45)',
  padding: '8px 11px',
  fontFamily: chart.fontUi,
  fontSize: 12,
}

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
