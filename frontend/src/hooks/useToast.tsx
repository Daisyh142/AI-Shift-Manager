/* eslint-disable react-refresh/only-export-components */
import { createContext, useCallback, useContext, useMemo, useState, type ReactNode } from 'react'

export interface ToastMessage {
  id: string
  title: string
  description?: string
  variant?: 'default' | 'error'
}

interface ToastContextValue {
  toasts: ToastMessage[]
  toast: (toast: Omit<ToastMessage, 'id'>) => void
  dismiss: (id: string) => void
}

const ToastContext = createContext<ToastContextValue | undefined>(undefined)

// Generates a unique ID for each toast message.
function uid() {
  return `${Date.now()}-${Math.random().toString(36).slice(2, 8)}`
}

// Provides toast state and the `toast()` trigger — auto-dismisses after 3.5 s.
export function ToastProvider({ children }: { children: ReactNode }) {
  const [toasts, setToasts] = useState<ToastMessage[]>([])

  const dismiss = useCallback((id: string) => {
    setToasts((prev) => prev.filter((toast) => toast.id !== id))
  }, [])

  const toast = useCallback((value: Omit<ToastMessage, 'id'>) => {
    const id = uid()
    setToasts((prev) => [{ id, ...value }, ...prev].slice(0, 4))
    window.setTimeout(() => {
      setToasts((prev) => prev.filter((item) => item.id !== id))
    }, 3500)
  }, [])

  const contextValue = useMemo(() => ({ toasts, toast, dismiss }), [dismiss, toast, toasts])
  return <ToastContext.Provider value={contextValue}>{children}</ToastContext.Provider>
}

// Hook to trigger toasts — must be used inside ToastProvider.
export function useToast() {
  const context = useContext(ToastContext)
  if (!context) {
    throw new Error('useToast must be used inside ToastProvider')
  }
  return context
}
