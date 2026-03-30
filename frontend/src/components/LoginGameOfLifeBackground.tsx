import { useEffect, useRef } from 'react'

/**
 * Conway's Game of Life (John Horton Conway): B3/S23
 * – lebende Zelle: überlebt bei 2 oder 3 lebenden Nachbarn
 * – tote Zelle: wird lebendig bei genau 3 lebenden Nachbarn
 * Raster endlich: hier feste Ränder (Nachbarn außerhalb = tot), kein Torus-Wrapping.
 */
/** Ziel-Zellgröße in CSS-Pixeln (höher = größere sichtbare Quadrate). */
const TARGET_CELL_PX = 10
/** Zeit zwischen Generationen (höher = langsamer). */
const STEP_MS = 400
const ALIVE_THRESHOLD = 0.32
const MIN_ALIVE_FRAC = 0.012

function countAlive(buf: Uint8Array): number {
  let n = 0
  for (let i = 0; i < buf.length; i++) n += buf[i]
  return n
}

function seedGrid(buf: Uint8Array): void {
  let p = ALIVE_THRESHOLD
  for (let attempt = 0; attempt < 3; attempt++) {
    for (let i = 0; i < buf.length; i++) {
      buf[i] = Math.random() < p ? 1 : 0
    }
    const alive = countAlive(buf)
    if (alive >= Math.max(32, Math.floor(buf.length * 0.004))) return
    p = Math.min(0.45, p + 0.06)
  }
}

/** Login-Hintergrund: Conway Life (B3/S23), feste tote Ränder; Viewport-großes Canvas. */
export default function LoginGameOfLifeBackground() {
  const wrapRef = useRef<HTMLDivElement>(null)
  const canvasRef = useRef<HTMLCanvasElement>(null)

  useEffect(() => {
    const wrap = wrapRef.current
    const canvas = canvasRef.current
    if (!wrap || !canvas) return

    const ctx = canvas.getContext('2d', { alpha: false })
    if (!ctx) return

    const c2d = ctx
    const canvasEl = canvas
    const wrapEl = wrap

    let cols = 0
    let rows = 0
    let cssW = 1
    let cssH = 1
    let cellW = 1
    let cellH = 1
    let gridA = new Uint8Array(0)
    let gridB = new Uint8Array(0)
    let raf = 0
    let lastStep = 0
    let reducedMotion = window.matchMedia('(prefers-reduced-motion: reduce)').matches

    const mq = window.matchMedia('(prefers-reduced-motion: reduce)')
    const onMq = () => {
      reducedMotion = mq.matches
    }
    mq.addEventListener('change', onMq)

    function step(): void {
      const c = cols
      const r = rows
      for (let y = 0; y < r; y++) {
        for (let x = 0; x < c; x++) {
          let n = 0
          for (let dy = -1; dy <= 1; dy++) {
            for (let dx = -1; dx <= 1; dx++) {
              if (dx === 0 && dy === 0) continue
              const nx = x + dx
              const ny = y + dy
              if (nx < 0 || nx >= c || ny < 0 || ny >= r) continue
              n += gridA[ny * c + nx]
            }
          }
          const i = y * c + x
          const alive = gridA[i]
          gridB[i] = alive ? (n === 2 || n === 3 ? 1 : 0) : n === 3 ? 1 : 0
        }
      }
      const t = gridA
      gridA = gridB
      gridB = t
    }

    function draw(): void {
      const root = getComputedStyle(document.documentElement)
      const bg = root.getPropertyValue('--color-background').trim() || '#0f1419'
      const accent = root.getPropertyValue('--color-primary').trim() || '#6366f1'

      c2d.fillStyle = bg
      c2d.fillRect(0, 0, cssW, cssH)

      const gap = 0.55
      c2d.fillStyle = accent
      for (let y = 0; y < rows; y++) {
        for (let x = 0; x < cols; x++) {
          if (gridA[y * cols + x]) {
            c2d.globalAlpha = 0.88
            c2d.fillRect(
              x * cellW,
              y * cellH,
              Math.max(0.5, cellW - gap),
              Math.max(0.5, cellH - gap)
            )
          }
        }
      }
      c2d.globalAlpha = 1
    }

    function viewportCssSize(): { w: number; h: number } {
      const vv = window.visualViewport
      const iw = window.innerWidth
      const ih = window.innerHeight
      const cw = document.documentElement.clientWidth
      const w = Math.max(vv?.width ?? 0, cw, iw)
      const h = Math.max(vv?.height ?? 0, ih)
      return { w: Math.max(1, w), h: Math.max(1, h) }
    }

    function layout(): void {
      const { w, h } = viewportCssSize()
      const dpr = Math.min(window.devicePixelRatio || 1, 2)
      cssW = w
      cssH = h
      canvasEl.width = Math.floor(cssW * dpr)
      canvasEl.height = Math.floor(cssH * dpr)
      canvasEl.style.width = `${cssW}px`
      canvasEl.style.height = `${cssH}px`
      c2d.setTransform(dpr, 0, 0, dpr, 0, 0)

      cols = Math.max(12, Math.ceil(cssW / TARGET_CELL_PX))
      rows = Math.max(12, Math.ceil(cssH / TARGET_CELL_PX))
      cellW = cssW / cols
      cellH = cssH / rows
      gridA = new Uint8Array(cols * rows)
      gridB = new Uint8Array(cols * rows)
      seedGrid(gridA)
      draw()
    }

    const ro = new ResizeObserver(() => layout())
    ro.observe(wrapEl)
    const onWinResize = () => layout()
    window.addEventListener('resize', onWinResize)

    const vv = window.visualViewport
    const onVvResize = () => layout()
    vv?.addEventListener('resize', onVvResize)

    layout()

    function tick(now: number): void {
      raf = requestAnimationFrame(tick)
      if (reducedMotion) return
      if (now - lastStep < STEP_MS) return
      lastStep = now
      step()
      const alive = countAlive(gridA)
      if (alive < Math.max(24, gridA.length * MIN_ALIVE_FRAC)) {
        seedGrid(gridA)
      }
      draw()
    }

    if (!reducedMotion) {
      raf = requestAnimationFrame(tick)
    }

    return () => {
      mq.removeEventListener('change', onMq)
      window.removeEventListener('resize', onWinResize)
      vv?.removeEventListener('resize', onVvResize)
      ro.disconnect()
      cancelAnimationFrame(raf)
    }
  }, [])

  return (
    <div ref={wrapRef} className="login-background-gameoflife-wrap">
      <canvas ref={canvasRef} className="login-background-gameoflife" aria-hidden />
    </div>
  )
}
