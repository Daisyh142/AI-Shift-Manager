import { useMemo, useState, type FormEvent, type ReactNode } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Link } from 'wouter'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { useAuth } from '@/hooks/useAuth'
import { apiClient } from '@/lib/api'
import { ScheduleGrid } from '@/components/ScheduleGrid'
import { TeamScheduleView } from '@/components/TeamScheduleView'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { useToast } from '@/hooks/useToast'
import { Calendar, Clock, Users } from 'lucide-react'
import { formatEtTime } from '@/lib/time'

function localIsoDate(date: Date) {
  const year = date.getFullYear()
  const month = String(date.getMonth() + 1).padStart(2, '0')
  const dayOfMonth = String(date.getDate()).padStart(2, '0')
  return `${year}-${month}-${dayOfMonth}`
}

export function EmployeeDashboard() {
  const { user } = useAuth()
  const employeeId = user?.employee_id
  const queryClient = useQueryClient()
  const { toast } = useToast()

  const employeeQuery = useQuery({
    queryKey: ['employee', employeeId],
    queryFn: () => apiClient.getEmployee(employeeId as string),
    enabled: Boolean(employeeId),
  })

  const requestsQuery = useQuery({
    queryKey: ['time-off-requests'],
    queryFn: () => apiClient.listTimeOffRequests(),
  })

  const coverageRequestsQuery = useQuery({
    queryKey: ['my-coverage-requests'],
    queryFn: () => apiClient.listMyCoverageRequests(),
    enabled: Boolean(employeeId),
  })

  const hoursRequestsQuery = useQuery({
    queryKey: ['my-hours-requests'],
    queryFn: () => apiClient.listMyHoursRequests(),
    enabled: Boolean(employeeId),
  })

  const employeesQuery = useQuery({
    queryKey: ['employees'],
    queryFn: () => apiClient.getEmployees(),
  })

  const shiftsQuery = useQuery({
    queryKey: ['shifts'],
    queryFn: () => apiClient.getShifts(),
  })

  const latestPublishedRunQuery = useQuery({
    queryKey: ['latest-schedule-run', 'published'],
    queryFn: () => apiClient.getLatestScheduleRun('published'),
  })

  const scheduleRunQuery = useQuery({
    queryKey: ['schedule-run', latestPublishedRunQuery.data?.schedule_run_id],
    queryFn: () => apiClient.getScheduleRun(latestPublishedRunQuery.data!.schedule_run_id),
    enabled: Boolean(latestPublishedRunQuery.data?.schedule_run_id),
  })

  const myRequests = useMemo(
    () => (requestsQuery.data ?? []).filter((request) => request.employee_id === employeeId),
    [employeeId, requestsQuery.data],
  )

  const myScheduleView = useMemo(() => {
    const scheduleRun = scheduleRunQuery.data
    if (!scheduleRun || !employeeId) return null

    return {
      ...scheduleRun,
      schedule: {
        ...scheduleRun.schedule,
        assignments: scheduleRun.schedule.assignments.filter((assignment) => assignment.employee_id === employeeId),
      },
    }
  }, [employeeId, scheduleRunQuery.data])

  const employeeNameById = useMemo(() => {
    if (!employeeQuery.data) return {}
    return { [employeeQuery.data.id]: employeeQuery.data.name }
  }, [employeeQuery.data])

  const publishedStart = scheduleRunQuery.data?.schedule.week_start_date ?? localIsoDate(new Date())
  const publishedStartDate = new Date(`${publishedStart}T00:00:00`)
  const publishedEndDate = new Date(publishedStartDate)
  publishedEndDate.setDate(publishedStartDate.getDate() + 13)
  const periodEndIso = localIsoDate(publishedEndDate)

  const availableCoverageShifts = useMemo(() => {
    const shifts = shiftsQuery.data ?? []
    return shifts
      .filter((shift) => shift.date >= publishedStart && shift.date <= periodEndIso)
      .sort((a, b) => a.date.localeCompare(b.date) || a.start_time.localeCompare(b.start_time))
  }, [periodEndIso, publishedStart, shiftsQuery.data])

  const [coverageShiftId, setCoverageShiftId] = useState<string>('')
  const [coverageReason, setCoverageReason] = useState('')
  const [hoursRequested, setHoursRequested] = useState('40')
  const [hoursNote, setHoursNote] = useState('')

  const createCoverageMutation = useMutation({
    mutationFn: () =>
      apiClient.createCoverageRequest({
        requester_employee_id: employeeId as string,
        shift_id: coverageShiftId,
        reason: coverageReason.trim() || undefined,
      }),
    onSuccess: () => {
      setCoverageReason('')
      setCoverageShiftId('')
      toast({ title: 'Coverage request submitted' })
      void queryClient.invalidateQueries({ queryKey: ['my-coverage-requests'] })
      void queryClient.invalidateQueries({ queryKey: ['pending-coverage-requests'] })
    },
    onError: (err) => {
      console.error('Coverage request submission failed', err)
      toast({
        title: 'Coverage request failed',
        description: err instanceof Error ? err.message : 'Unable to submit coverage request.',
        variant: 'error',
      })
    },
  })

  const createHoursMutation = useMutation({
    mutationFn: () =>
      apiClient.createHoursRequest({
        employee_id: employeeId as string,
        period_start: publishedStart,
        period_end: periodEndIso,
        requested_hours: Number(hoursRequested),
        note: hoursNote.trim() || undefined,
      }),
    onSuccess: () => {
      setHoursNote('')
      toast({ title: 'Hours request submitted' })
      void queryClient.invalidateQueries({ queryKey: ['my-hours-requests'] })
      void queryClient.invalidateQueries({ queryKey: ['pending-hours-requests'] })
    },
    onError: (err) => {
      console.error('Hours request submission failed', err)
      toast({
        title: 'Hours request failed',
        description: err instanceof Error ? err.message : 'Unable to submit hours request.',
        variant: 'error',
      })
    },
  })

  function submitCoverage(event: FormEvent) {
    event.preventDefault()
    if (!employeeId || !coverageShiftId) return
    createCoverageMutation.mutate()
  }

  function submitHours(event: FormEvent) {
    event.preventDefault()
    if (!employeeId) return
    createHoursMutation.mutate()
  }

  return (
    <section className="space-y-6">
      <header className="space-y-2">
        <p className="text-xs font-semibold uppercase tracking-[0.16em] text-muted-foreground">Employee dashboard</p>
        <h1 className="text-3xl font-bold tracking-tight">Your Weekly Workspace</h1>
        <p className="text-sm text-muted-foreground">
          Track your schedule, check team coverage, and manage your own requests in one place.
        </p>
      </header>

      <div className="grid gap-4 sm:grid-cols-3">
        <StatCard icon={<Clock className="h-4 w-4" />} label="Required This Week" value={employeeQuery.data ? `${employeeQuery.data.required_weekly_hours.toFixed(1)}h` : '...'} />
        <StatCard icon={<Calendar className="h-4 w-4" />} label="Max Weekly Hours" value={employeeQuery.data ? `${employeeQuery.data.max_weekly_hours.toFixed(1)}h` : '...'} />
        <StatCard icon={<Users className="h-4 w-4" />} label="PTO Balance" value={employeeQuery.data ? `${employeeQuery.data.pto_balance_hours.toFixed(1)}h` : '...'} />
      </div>

      <div className="grid gap-3 sm:grid-cols-3">
        <Link href="/my-requests">
          <Button className="w-full justify-start" variant="outline">
            Request PTO / time off
          </Button>
        </Link>
        <Link href="/team-schedule">
          <Button className="w-full justify-start" variant="outline">
            View full team schedule
          </Button>
        </Link>
        <Button className="w-full justify-start" variant="outline">
          Coverage requests now available below
        </Button>
      </div>

      {myScheduleView && shiftsQuery.data ? (
        <ScheduleGrid
          employeeNameById={employeeNameById}
          emptyMessage="You have no assigned shifts in the latest published schedule."
          onlyAssignedShifts
          scheduleRun={myScheduleView}
          shifts={shiftsQuery.data}
          title="My Schedule"
        />
      ) : (
        <Card>
          <CardHeader>
            <CardTitle className="text-lg">My Schedule</CardTitle>
          </CardHeader>
          <CardContent className="text-sm text-muted-foreground">
            No published schedule yet. Ask the owner to generate and publish a schedule.
          </CardContent>
        </Card>
      )}

      {scheduleRunQuery.data && shiftsQuery.data && employeesQuery.data ? (
        <TeamScheduleView
          assignments={scheduleRunQuery.data.schedule.assignments}
          currentEmployeeId={employeeId ?? null}
          employees={employeesQuery.data}
          shifts={shiftsQuery.data}
          weekStartDate={scheduleRunQuery.data.schedule.week_start_date}
        />
      ) : null}

      <Card>
        <CardHeader>
          <CardTitle className="text-lg">Recent Activity</CardTitle>
        </CardHeader>
        <CardContent>
          {myRequests.length === 0 ? (
            <p className="text-sm text-muted-foreground">No request activity yet.</p>
          ) : (
            <div className="space-y-2">
              {myRequests.map((request) => (
                <div className="rounded-xl border border-border/80 bg-muted/35 p-3 text-sm" key={request.id}>
                  <p className="font-medium">
                    {request.kind.toUpperCase()} - {request.date}
                  </p>
                  <p className="text-muted-foreground">Status: {request.status}</p>
                  {request.reason ? <p className="text-muted-foreground">Reason: {request.reason}</p> : null}
                </div>
              ))}
            </div>
          )}
        </CardContent>
      </Card>

      <Card className="border-primary/15">
        <CardHeader>
          <CardTitle className="text-lg">Request Shift Coverage</CardTitle>
        </CardHeader>
        <CardContent>
          <form className="grid gap-3 md:grid-cols-2" onSubmit={submitCoverage}>
            <label className="text-sm">
              Shift
              <select
                className="mt-1 h-10 w-full rounded-[12px] border border-input bg-background/90 px-3 text-sm text-foreground transition-all focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
                onChange={(event) => setCoverageShiftId(event.target.value)}
                required
                value={coverageShiftId}
              >
                <option value="">Select a shift</option>
                {availableCoverageShifts.map((shift) => (
                  <option key={shift.id} value={shift.id}>
                    {shift.date} · {formatEtTime(shift.start_time)} - {formatEtTime(shift.end_time)}
                  </option>
                ))}
              </select>
            </label>
            <label className="text-sm">
              Reason
              <Input onChange={(event) => setCoverageReason(event.target.value)} placeholder="Optional reason" value={coverageReason} />
            </label>
            <div className="md:col-span-2">
              <Button disabled={createCoverageMutation.isPending} type="submit">
                Submit Coverage Request
              </Button>
            </div>
          </form>
          <div className="mt-4 space-y-2">
            <p className="text-sm font-semibold">My Coverage Requests</p>
            {(coverageRequestsQuery.data ?? []).length === 0 ? (
              <p className="text-sm text-muted-foreground">No coverage requests yet.</p>
            ) : (
              (coverageRequestsQuery.data ?? []).map((request) => (
                <div className="rounded-xl border border-border/80 bg-muted/35 p-3 text-sm" key={request.id}>
                  <p className="font-medium">Shift #{request.shift_id}</p>
                  <p className="text-muted-foreground">Status: {request.status}</p>
                  {request.reason ? <p className="text-muted-foreground">Reason: {request.reason}</p> : null}
                  {request.cover_employee_id ? <p className="text-muted-foreground">Cover employee: {request.cover_employee_id}</p> : null}
                </div>
              ))
            )}
          </div>
        </CardContent>
      </Card>

      <Card className="border-primary/15">
        <CardHeader>
          <CardTitle className="text-lg">Request More/Less Hours (Pay Period)</CardTitle>
        </CardHeader>
        <CardContent>
          <form className="grid gap-3 md:grid-cols-2" onSubmit={submitHours}>
            <label className="text-sm">
              Period Start
              <Input disabled value={publishedStart} />
            </label>
            <label className="text-sm">
              Period End
              <Input disabled value={periodEndIso} />
            </label>
            <label className="text-sm">
              Requested Hours (0-80)
              <Input max="80" min="0" onChange={(event) => setHoursRequested(event.target.value)} required step="1" type="number" value={hoursRequested} />
            </label>
            <label className="text-sm">
              Note
              <Input onChange={(event) => setHoursNote(event.target.value)} placeholder="Optional note" value={hoursNote} />
            </label>
            <div className="md:col-span-2">
              <Button disabled={createHoursMutation.isPending} type="submit">
                Submit Hours Request
              </Button>
            </div>
          </form>
          <div className="mt-4 space-y-2">
            <p className="text-sm font-semibold">My Hours Requests</p>
            {(hoursRequestsQuery.data ?? []).length === 0 ? (
              <p className="text-sm text-muted-foreground">No hours requests yet.</p>
            ) : (
              (hoursRequestsQuery.data ?? []).map((request) => (
                <div className="rounded-xl border border-border/80 bg-muted/35 p-3 text-sm" key={request.id}>
                  <p className="font-medium">
                    {request.period_start} to {request.period_end}
                  </p>
                  <p className="text-muted-foreground">Requested: {request.requested_hours}h</p>
                  <p className="text-muted-foreground">Status: {request.status}</p>
                  {request.note ? <p className="text-muted-foreground">Note: {request.note}</p> : null}
                </div>
              ))
            )}
          </div>
        </CardContent>
      </Card>
    </section>
  )
}

function StatCard({ icon, label, value }: { icon: ReactNode; label: string; value: string }) {
  return (
    <Card className="border-border/70">
      <CardContent className="p-4">
        <div className="mb-2 flex items-center gap-2 text-muted-foreground">
          {icon}
          <span className="text-sm">{label}</span>
        </div>
        <p className="text-2xl font-bold text-foreground">{value}</p>
      </CardContent>
    </Card>
  )
}
