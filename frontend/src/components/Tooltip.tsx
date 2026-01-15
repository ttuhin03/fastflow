import { useState, useRef, useEffect, useCallback } from 'react'
import './Tooltip.css'

interface TooltipProps {
  content: string
  children: React.ReactNode
  position?: 'top' | 'bottom' | 'left' | 'right'
  delay?: number
}

export default function Tooltip({
  content,
  children,
  position = 'top',
  delay = 300,
}: TooltipProps) {
  const [isVisible, setIsVisible] = useState(false)
  const [tooltipPosition, setTooltipPosition] = useState<{ top: number; left: number } | null>(
    null
  )
  const timeoutRef = useRef<ReturnType<typeof setTimeout> | null>(null)
  const triggerRef = useRef<HTMLDivElement>(null)
  const tooltipRef = useRef<HTMLDivElement>(null)

  const showTooltip = () => {
    if (timeoutRef.current) {
      clearTimeout(timeoutRef.current)
    }
    timeoutRef.current = setTimeout(() => {
      setIsVisible(true)
    }, delay)
  }

  const hideTooltip = () => {
    if (timeoutRef.current) {
      clearTimeout(timeoutRef.current)
    }
    setIsVisible(false)
    setTooltipPosition(null)
  }

  const updateTooltipPosition = useCallback(() => {
    if (!triggerRef.current || !tooltipRef.current) return

    const triggerRect = triggerRef.current.getBoundingClientRect()
    const tooltipRect = tooltipRef.current.getBoundingClientRect()
    
    // Prüfe ob Tooltip-Element bereits gemessen werden kann (width > 0)
    if (tooltipRect.width === 0 || tooltipRect.height === 0) {
      // Versuche es nochmal nach kurzer Verzögerung
      setTimeout(() => updateTooltipPosition(), 10)
      return
    }

    // Verwende position: fixed mit viewport-koordinaten (getBoundingClientRect)
    // Keine Scroll-Offsets nötig, da fixed relativ zum Viewport ist
    let top = 0
    let left = 0

    switch (position) {
      case 'top':
        top = triggerRect.top - tooltipRect.height - 8
        left = triggerRect.left + triggerRect.width / 2 - tooltipRect.width / 2
        break
      case 'bottom':
        top = triggerRect.bottom + 8
        left = triggerRect.left + triggerRect.width / 2 - tooltipRect.width / 2
        break
      case 'left':
        top = triggerRect.top + triggerRect.height / 2 - tooltipRect.height / 2
        left = triggerRect.left - tooltipRect.width - 8
        break
      case 'right':
        top = triggerRect.top + triggerRect.height / 2 - tooltipRect.height / 2
        left = triggerRect.right + 8
        break
    }

    setTooltipPosition({ top, left })
  }, [position])

  useEffect(() => {
    if (isVisible) {
      // Warte bis das Tooltip-Element im DOM gerendert ist
      // Verwende mehrfache requestAnimationFrame für zuverlässiges Rendering
      let rafId: number
      const updatePosition = () => {
        rafId = requestAnimationFrame(() => {
          requestAnimationFrame(() => {
            updateTooltipPosition()
            // Nochmal nach kurzer Verzögerung für Sicherheit
            setTimeout(() => {
              updateTooltipPosition()
            }, 0)
          })
        })
      }
      
      updatePosition()
      
      window.addEventListener('scroll', updateTooltipPosition, true)
      window.addEventListener('resize', updateTooltipPosition)
      
      return () => {
        if (rafId) cancelAnimationFrame(rafId)
        window.removeEventListener('scroll', updateTooltipPosition, true)
        window.removeEventListener('resize', updateTooltipPosition)
      }
    }
  }, [isVisible, content, position, updateTooltipPosition])

  useEffect(() => {
    return () => {
      if (timeoutRef.current) {
        clearTimeout(timeoutRef.current)
      }
    }
  }, [])

  return (
    <div
      ref={triggerRef}
      className="tooltip-trigger"
      onMouseEnter={showTooltip}
      onMouseLeave={hideTooltip}
      onFocus={showTooltip}
      onBlur={hideTooltip}
    >
      {children}
      {isVisible && (
        <div
          ref={tooltipRef}
          className={`tooltip tooltip-${position}`}
          style={
            tooltipPosition
              ? {
                  top: `${tooltipPosition.top}px`,
                  left: `${tooltipPosition.left}px`,
                  visibility: 'visible',
                }
              : {
                  visibility: 'hidden',
                  top: '-9999px',
                  left: '-9999px',
                }
          }
        >
          {content}
        </div>
      )}
    </div>
  )
}
