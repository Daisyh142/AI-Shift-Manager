import type { TimeOffRequestResponse } from '@/lib/api'
import { Button } from '@/components/ui/button'
import { Calendar, Check, Clock, X } from 'lucide-react'
import { cn } from '@/lib/utils'

interface RequestCardProps {
  request: TimeOffRequestResponse
  employeeName: string
  onApprove?: () => void
  onDeny?: () => void
  isBusy?: boolean
}

export function RequestCard({ request, employeeName, onApprove, onDeny, isBusy }: RequestCardProps) {
  const isPending = request.status === 'pending'
  const statusClassName = {
    pending: 'bg-[color:var(--warning)]/15 text-[color:var(--warning)]',
    approved: 'bg-[color:var(--success)]/15 text-[color:var(--success)]',
    denied: 'bg-destructive/15 text-destructive',
  }[request.status]

  const typeLabel = request.kind === 'pto' ? 'PTO Request' : 'Request Off'

  return (
    <article className="rounded-xl border border-border/65 bg-gradient-to-br from-card via-card to-muted/25 p-4 transition-all hover:shadow-card">
      <div className="flex items-start gap-3">
        <div className="rounded-lg bg-primary/10 p-2 text-primary">
          {request.kind === 'pto' ? <Calendar className="h-4 w-4" /> : <Clock className="h-4 w-4" />}
        </div>
        <div className="min-w-0 flex-1">
          <div className="flex items-start justify-between gap-3">
            <div>
              <p className="text-xs font-medium text-muted-foreground">{typeLabel}</p>
              <h4 className="mt-1 font-semibold text-foreground">{employeeName}</h4>
            </div>
            <span className={cn('rounded-full px-2.5 py-1 text-xs font-semibold capitalize', statusClassName)}>
              {request.status}
            </span>
          </div>
          <p className="mt-1 text-sm text-muted-foreground">{request.date}</p>
          {request.reason ? <p className="mt-2 text-sm text-muted-foreground">{request.reason}</p> : null}
          {isPending && onApprove && onDeny ? (
            <div className="mt-3 flex gap-2">
              <Button disabled={isBusy} onClick={onApprove} size="sm" variant="success">
                <Check className="h-3.5 w-3.5" />
                Approve
              </Button>
              <Button disabled={isBusy} onClick={onDeny} size="sm" variant="destructive">
                <X className="h-3.5 w-3.5" />
                Deny
              </Button>
            </div>
          ) : null}
        </div>
      </div>
    </article>
  )
}
