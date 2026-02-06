/**
 * Component-Tests für ProgressBar.
 */

import { describe, it, expect } from 'vitest'
import { render, screen } from '@testing-library/react'
import ProgressBar from './ProgressBar'

describe('ProgressBar', () => {
  it('rendert Erfolgsrate-Label und Wert', () => {
    render(<ProgressBar value={75} />)
    expect(screen.getByText('Erfolgsrate:')).toBeInTheDocument()
    expect(screen.getByText('75.0%')).toBeInTheDocument()
  })

  it('rendert ohne Label wenn showLabel=false', () => {
    render(<ProgressBar value={50} showLabel={false} />)
    expect(screen.queryByText('Erfolgsrate:')).not.toBeInTheDocument()
  })

  it('clampet Wert auf 0-100 für die Breite', () => {
    const { container } = render(<ProgressBar value={150} showLabel={false} />)
    const fill = container.querySelector('.progress-bar-fill')
    expect(fill).toHaveStyle({ width: '100%' })
  })

  it('clampet negativen Wert auf 0', () => {
    const { container } = render(<ProgressBar value={-10} showLabel={false} />)
    const fill = container.querySelector('.progress-bar-fill')
    expect(fill).toHaveStyle({ width: '0%' })
  })

  it('fügt progress-high Klasse bei Wert >= 80', () => {
    const { container } = render(<ProgressBar value={80} showLabel={false} />)
    const fill = container.querySelector('.progress-bar-fill')
    expect(fill).toHaveClass('progress-high')
  })

  it('fügt progress-medium Klasse bei Wert >= 50 und < 80', () => {
    const { container } = render(<ProgressBar value={50} showLabel={false} />)
    const fill = container.querySelector('.progress-bar-fill')
    expect(fill).toHaveClass('progress-medium')
  })

  it('fügt progress-low Klasse bei Wert < 50', () => {
    const { container } = render(<ProgressBar value={25} showLabel={false} />)
    const fill = container.querySelector('.progress-bar-fill')
    expect(fill).toHaveClass('progress-low')
  })
})
