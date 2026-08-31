import { createContext, useCallback, useContext, useMemo, useRef, useState, type ReactNode } from 'react'

export type LipsyncTaskState = {
  busy: boolean
  progress: number
  message: string
  log: string
}

type LipsyncTaskContextValue = LipsyncTaskState & {
  setBusy: (busy: boolean) => void
  setProgress: (progress: number, message?: string) => void
  setLog: (log: string) => void
  reset: () => void
  setCancelHandler: (fn: (() => void | Promise<void>) | null) => void
  cancel: () => Promise<void>
}

const defaultState: LipsyncTaskState = {
  busy: false,
  progress: 0,
  message: '',
  log: '',
}

const LipsyncTaskContext = createContext<LipsyncTaskContextValue | null>(null)

export function LipsyncTaskProvider({ children }: { children: ReactNode }) {
  const [state, setState] = useState<LipsyncTaskState>(defaultState)
  const cancelRef = useRef<(() => void | Promise<void>) | null>(null)

  const setBusy = useCallback((busy: boolean) => {
    setState((s) => ({ ...s, busy }))
  }, [])

  const setProgress = useCallback((progress: number, message = '') => {
    setState((s) => ({ ...s, progress, message: message || s.message }))
  }, [])

  const setLog = useCallback((log: string) => {
    setState((s) => ({ ...s, log }))
  }, [])

  const reset = useCallback(() => {
    cancelRef.current = null
    setState(defaultState)
  }, [])

  const setCancelHandler = useCallback((fn: (() => void | Promise<void>) | null) => {
    cancelRef.current = fn
  }, [])

  const cancel = useCallback(async () => {
    const fn = cancelRef.current
    if (fn) await fn()
  }, [])

  const value = useMemo(
    () => ({ ...state, setBusy, setProgress, setLog, reset, setCancelHandler, cancel }),
    [state, setBusy, setProgress, setLog, reset, setCancelHandler, cancel],
  )

  return <LipsyncTaskContext.Provider value={value}>{children}</LipsyncTaskContext.Provider>
}

export function useLipsyncTask() {
  const ctx = useContext(LipsyncTaskContext)
  if (!ctx) throw new Error('useLipsyncTask must be used within LipsyncTaskProvider')
  return ctx
}
