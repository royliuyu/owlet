import { useEffect, useState } from 'react'

export type Breakpoint = 'mobile' | 'tablet' | 'desktop' | 'wide'

export function useBreakpoint(): Breakpoint {
  const [width, setWidth] = useState(() => window.innerWidth)
  useEffect(() => {
    const onResize = () => setWidth(window.innerWidth)
    window.addEventListener('resize', onResize)
    return () => window.removeEventListener('resize', onResize)
  }, [])
  if (width < 640) return 'mobile'
  if (width < 1280) return 'tablet'
  if (width < 1440) return 'desktop'
  return 'wide'
}

export type ReaderSpan = 'split' | 'max' | 'min'

export function useStoredString<T extends string>(
  key: string,
  fallback: T,
  allowed: readonly T[],
): [T, (value: T) => void] {
  const [value, setValue] = useState<T>(() => {
    const raw = localStorage.getItem(key)
    return raw !== null && (allowed as readonly string[]).includes(raw) ? (raw as T) : fallback
  })
  useEffect(() => {
    localStorage.setItem(key, value)
  }, [key, value])
  return [value, setValue]
}

export function useStoredNumber(key: string, fallback: number): [number, (value: number) => void] {
  const [value, setValue] = useState(() => {
    const raw = localStorage.getItem(key)
    const parsed = raw ? Number(raw) : fallback
    return Number.isFinite(parsed) ? parsed : fallback
  })
  useEffect(() => {
    localStorage.setItem(key, String(value))
  }, [key, value])
  return [value, setValue]
}
