import { useCallback, useEffect, useState } from 'react'

interface UseMeasuredChartWidthOptions {
  minWidth?: number
}

function resolveMeasuredWidth(element: HTMLElement | null, minWidth: number): number {
  if (!element) {
    return 0
  }

  const nextWidth = Math.round(element.getBoundingClientRect().width)
  if (!Number.isFinite(nextWidth) || nextWidth <= 0) {
    return 0
  }

  return Math.max(nextWidth, minWidth)
}

function useMeasuredChartWidth<T extends HTMLElement = HTMLDivElement>({
  minWidth = 0,
}: UseMeasuredChartWidthOptions = {}) {
  const [element, setElement] = useState<T | null>(null)
  const [width, setWidth] = useState(0)
  const containerRef = useCallback((node: T | null) => {
    setElement(node)
    if (!node) {
      setWidth(0)
    }
  }, [])

  useEffect(() => {
    if (!element) {
      return
    }

    const updateWidth = () => {
      setWidth((currentWidth) => {
        const nextWidth = resolveMeasuredWidth(element, minWidth)
        return currentWidth === nextWidth ? currentWidth : nextWidth
      })
    }

    const frameId = window.requestAnimationFrame(updateWidth)
    let resizeObserver: ResizeObserver | null = null

    if (typeof ResizeObserver !== 'undefined') {
      resizeObserver = new ResizeObserver(() => {
        updateWidth()
      })
      resizeObserver.observe(element)
    }

    window.addEventListener('resize', updateWidth)

    return () => {
      window.cancelAnimationFrame(frameId)
      resizeObserver?.disconnect()
      window.removeEventListener('resize', updateWidth)
    }
  }, [element, minWidth])

  return { containerRef, width }
}

export default useMeasuredChartWidth
