import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useSyncExternalStore,
  type ReactNode,
} from 'react'

export const KEY_SHOW_ATTRIBUTION = 'fastflow_ui_show_attribution'
export const KEY_SHOW_VERSION = 'fastflow_ui_show_version'

function readBool(key: string, defaultVal: boolean): boolean {
  try {
    const v = localStorage.getItem(key)
    if (v === null) return defaultVal
    return v === '1' || v === 'true'
  } catch {
    return defaultVal
  }
}

function writeBool(key: string, value: boolean) {
  try {
    localStorage.setItem(key, value ? '1' : '0')
  } catch {
    /* ignore */
  }
}

const listeners = new Set<() => void>()

function computeSnapshot(): { showAttribution: boolean; showVersion: boolean } {
  return {
    showAttribution: readBool(KEY_SHOW_ATTRIBUTION, true),
    showVersion: readBool(KEY_SHOW_VERSION, true),
  }
}

/** Cached reference — useSyncExternalStore requires the same object when values are unchanged. */
let snapshotCache = computeSnapshot()

function publishSnapshot() {
  const next = computeSnapshot()
  if (
    next.showAttribution === snapshotCache.showAttribution &&
    next.showVersion === snapshotCache.showVersion
  ) {
    return
  }
  snapshotCache = next
  listeners.forEach((l) => l())
}

function subscribe(callback: () => void) {
  listeners.add(callback)
  return () => {
    listeners.delete(callback)
  }
}

function getSnapshot() {
  return snapshotCache
}

type UiPrefs = {
  showAttribution: boolean
  showVersion: boolean
  setShowAttribution: (v: boolean) => void
  setShowVersion: (v: boolean) => void
}

const Context = createContext<UiPrefs | null>(null)

export function UiPreferencesProvider({ children }: { children: ReactNode }) {
  const snap = useSyncExternalStore(subscribe, getSnapshot, getSnapshot)

  useEffect(() => {
    const onStorage = (e: StorageEvent) => {
      if (e.key === KEY_SHOW_ATTRIBUTION || e.key === KEY_SHOW_VERSION) publishSnapshot()
    }
    window.addEventListener('storage', onStorage)
    return () => window.removeEventListener('storage', onStorage)
  }, [])

  const setShowAttribution = useCallback((v: boolean) => {
    writeBool(KEY_SHOW_ATTRIBUTION, v)
    publishSnapshot()
  }, [])
  const setShowVersion = useCallback((v: boolean) => {
    writeBool(KEY_SHOW_VERSION, v)
    publishSnapshot()
  }, [])

  const value = useMemo(
    () => ({
      ...snap,
      setShowAttribution,
      setShowVersion,
    }),
    [snap, setShowAttribution, setShowVersion]
  )

  return <Context.Provider value={value}>{children}</Context.Provider>
}

export function useUiPreferences(): UiPrefs {
  const c = useContext(Context)
  if (!c) throw new Error('useUiPreferences must be used within UiPreferencesProvider')
  return c
}
