import { useMemo, useState, type FormEvent } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { apiClient, type TimeOffRequestResponse } from '@/lib/api'
import { useAuth } from '@/hooks/useAuth'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import { Button } from '@/components/ui/button'
import { RequestCard } from '@/components/RequestCard'
import { useToast } from '@/hooks/useToast'
import { Calendar, ClipboardList } from 'lucide-react'

function getDefaultDatePlusDays(days: number) {
  const date = new Date()
  date.setDate(date.getDate() + days)
  return date.toISOString().slice(0, 10)
}

const ERROR_MESSAGES: Record<string, string> = {
  time_off_must_be_2_weeks_in_advance: 'Requests must be submitted at least 2 weeks in advance.',
  pto_hours_required: 'Please enter a valid number of PTO hours.',
  insufficient_pto_use_request_off: "You don't have enough PTO hours. Try submitting a Request Off instead.",
  employee_not_found: 'Employee record not found. Please contact your manager.',
  request_not_found: 'Request not found.',
  time_off_capacity_reached_keep_75_percent_available:
    'This date is at capacity — too many team members are already off. Please choose another date.',
  cannot_approve_pto_insufficient_balance: 'This employee has insufficient PTO balance to approve this request.',
}

function friendlyError(err: unknown): string {
  const raw = err instanceof Error ? err.message : ''
  return ERROR_MESSAGES[raw] ?? (raw || 'Something went wrong. Please try again.')
}

export function TimeOffRequests() {
  const queryClient = useQueryClient()
  const { toast } = useToast()
  const { user } = useAuth()
  const isOwner = user?.role === 'owner'
  const employeeId = user?.employee_id

  const [date, setDate] = useState(getDefaultDatePlusDays(14))
  const [kind, setKind] = useState<'pto' | 'request_off'>('request_off')
  const [hours, setHours] = useState('8')
  const [reason, setReason] = useState('')
  const [error, setError] = useState<string | null>(null)

  const employeesQuery = useQuery({
    queryKey: ['employees'],
    queryFn: () => apiClient.getEmployees(),
  })

  const requestsQuery = useQuery({
    queryKey: ['time-off-requests'],
    queryFn: () => apiClient.listTimeOffRequests(),
  })

  const createMutation = useMutation({
    mutationFn: () =>
      apiClient.createTimeOffRequest({
        employee_id: employeeId as string,
        date,
        kind,
        hours: kind === 'pto' ? Number(hours || 0) : 0,
        reason: reason.trim() || undefined,
      }),
    onSuccess: () => {
      setReason('')
      setError(null)
      toast({
        title: 'Request submitted',
        description: 'Your time-off request was sent for review.',
      })
      void queryClient.invalidateQueries({ queryKey: ['time-off-requests'] })
    },
    onError: (err) => {
      console.error('Time-off submit failed', err)
      const message = friendlyError(err)
      setError(message)
      toast({ title: 'Submit failed', description: message, variant: 'error' })
    },
  })

  const approveMutation = useMutation({
    mutationFn: (requestId: number) => apiClient.approveTimeOff(requestId),
    onSuccess: () => {
      toast({ title: 'Request approved' })
      void queryClient.invalidateQueries({ queryKey: ['time-off-requests'] })
    },
    onError: (err) => {
      console.error('Time-off approval failed', err)
      toast({ title: 'Approval failed', description: friendlyError(err), variant: 'error' })
    },
  })

  const denyMutation = useMutation({
    mutationFn: (requestId: number) => apiClient.denyTimeOff(requestId),
    onSuccess: () => {
      toast({ title: 'Request denied' })
      void queryClient.invalidateQueries({ queryKey: ['time-off-requests'] })
    },
    onError: (err) => {
      console.error('Time-off denial failed', err)
      toast({ title: 'Action failed', description: friendlyError(err), variant: 'error' })
    },
  })

  const employeeNameById = useMemo(() => {
    return Object.fromEntries((employeesQuery.data ?? []).map((employee) => [employee.id, employee.name]))
  }, [employeesQuery.data])

  const visibleRequests = useMemo<TimeOffRequestResponse[]>(() => {
    const all = requestsQuery.data ?? []
    if (isOwner) return all
    return all.filter((request) => request.employee_id === employeeId)
  }, [employeeId, isOwner, requestsQuery.data])

  function handleSubmit(event: FormEvent) {
    event.preventDefault()
    if (!employeeId) return
    createMutation.mutate()
  }

  return (
    <section className="space-y-6">
      <header className="space-y-2 rounded-2xl border border-border/65 bg-gradient-hero p-5">
        <p className="text-xs font-semibold uppercase tracking-[0.16em] text-muted-foreground">
          {isOwner ? 'Request management' : 'My requests'}
        </p>
        <h1 className="text-3xl font-bold tracking-tight">{isOwner ? 'Review Team Requests' : 'Submit Time-Off Requests'}</h1>
        <p className="text-sm text-muted-foreground">
          {isOwner ? 'Review pending requests directly from this queue.' : 'Create PTO or day-off requests and track their status.'}
        </p>
      </header>

      {requestsQuery.isLoading ? <p className="text-sm text-muted-foreground">Loading requests...</p> : null}
      {requestsQuery.isError ? (
        <p className="text-sm text-destructive">Failed to load requests. Please refresh the page.</p>
      ) : null}

      {!isOwner ? (
        <Card className="border-primary/15">
          <CardHeader>
            <CardTitle className="flex items-center gap-2 text-lg">
              <Calendar className="h-4 w-4 text-primary" />
              Submit Time Off Request
            </CardTitle>
          </CardHeader>
          <CardContent>
            <form className="grid gap-3 md:grid-cols-2" onSubmit={handleSubmit}>
              <label className="text-sm">
                Date
                <Input onChange={(event) => setDate(event.target.value)} required type="date" value={date} />
              </label>
              <label className="text-sm">
                Type
                <select
                  className="mt-1 h-10 w-full rounded-[12px] border border-input bg-background/90 px-3 text-sm text-foreground transition-all focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
                  onChange={(event) => setKind(event.target.value as 'pto' | 'request_off')}
                  value={kind}
                >
                  <option value="request_off">Request Off</option>
                  <option value="pto">PTO</option>
                </select>
              </label>
              {kind === 'pto' ? (
                <label className="text-sm">
                  Hours
                  <Input min="0" onChange={(event) => setHours(event.target.value)} step="0.5" type="number" value={hours} />
                </label>
              ) : null}
              <label className="text-sm md:col-span-2">
                Reason
                <Input onChange={(event) => setReason(event.target.value)} placeholder="Optional reason" value={reason} />
              </label>
              {error ? <p className="text-sm text-destructive md:col-span-2">{error}</p> : null}
              <div className="md:col-span-2">
                <Button disabled={createMutation.isPending} type="submit">
                  Submit Request
                </Button>
              </div>
            </form>
          </CardContent>
        </Card>
      ) : null}

      <div className="space-y-3">
        <h2 className="flex items-center gap-2 text-xl font-semibold">
          <ClipboardList className="h-4 w-4 text-primary" />
          {isOwner ? 'All Requests' : 'My Requests'}
        </h2>
        {!requestsQuery.isLoading && !requestsQuery.isError && visibleRequests.length === 0 ? (
          <p className="text-sm text-muted-foreground">No requests found.</p>
        ) : (
          <div className="grid gap-3 lg:grid-cols-2">
            {visibleRequests.map((request) => (
              <RequestCard
                employeeName={employeeNameById[request.employee_id] ?? request.employee_id}
                isBusy={isOwner ? approveMutation.isPending || denyMutation.isPending : undefined}
                key={request.id}
                onApprove={isOwner ? () => approveMutation.mutate(request.id) : undefined}
                onDeny={isOwner ? () => denyMutation.mutate(request.id) : undefined}
                request={request}
              />
            ))}
          </div>
        )}
      </div>
    </section>
  )
}
