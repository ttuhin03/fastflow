import { useTranslation } from 'react-i18next'
import './ProgressBar.css'

interface ProgressBarProps {
  value: number // 0-100
  showLabel?: boolean
  className?: string
}

export default function ProgressBar({ value, showLabel = true, className = '' }: ProgressBarProps) {
  const { t } = useTranslation()

  const getColorClass = () => {
    if (value >= 80) return 'progress-high'
    if (value >= 50) return 'progress-medium'
    return 'progress-low'
  }

  const clampedValue = Math.max(0, Math.min(100, value))

  return (
    <div className={`progress-bar-container ${className}`}>
      {showLabel && (
        <div className="progress-bar-label">
          <span>{t('calendar.successRate')}</span>
          <span className="progress-bar-value">{value.toFixed(1)}%</span>
        </div>
      )}
      <div className="progress-bar-track">
        <div
          className={`progress-bar-fill ${getColorClass()}`}
          style={{ width: `${clampedValue}%` }}
        />
      </div>
    </div>
  )
}
