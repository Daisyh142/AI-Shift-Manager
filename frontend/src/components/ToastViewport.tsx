import { useToast } from '@/hooks/useToast'

export function ToastViewport() {
  const { toasts, dismiss } = useToast()

  return (
    <div className="pointer-events-none fixed right-4 top-4 z-50 flex w-[min(92vw,360px)] flex-col gap-2">
      {toasts.map((toast) => (
        <div
          className={`pointer-events-auto rounded-xl border bg-card/95 p-3 shadow-[0_12px_24px_rgba(15,118,110,0.16)] ${
            toast.variant === 'error' ? 'border-destructive' : 'border-primary/20'
          }`}
          key={toast.id}
          role="status"
        >
          <div className="flex items-start justify-between gap-2">
            <div>
              <p className="text-sm font-semibold">{toast.title}</p>
              {toast.description ? <p className="text-xs text-muted-foreground">{toast.description}</p> : null}
            </div>
            <button
              aria-label="Dismiss notification"
              className="text-xs font-semibold text-muted-foreground hover:text-foreground"
              onClick={() => dismiss(toast.id)}
              type="button"
            >
              x
            </button>
          </div>
        </div>
      ))}
    </div>
  )
}
