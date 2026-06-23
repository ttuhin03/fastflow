import { LuInfo } from 'react-icons/lu'
import Tooltip from './Tooltip'
import './InfoIcon.css'

interface InfoIconProps {
  content: string
  position?: 'top' | 'bottom' | 'left' | 'right'
  className?: string
}

export default function InfoIcon({ 
  content, 
  position = 'top',
  className = '' 
}: InfoIconProps) {
  return (
    <Tooltip content={content} position={position}>
      <span className={`info-icon ${className}`} aria-label="Information">
        <LuInfo />
      </span>
    </Tooltip>
  )
}
