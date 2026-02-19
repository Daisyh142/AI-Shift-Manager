import { useMemo, useState, type ReactNode } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { ApiError, apiClient } from '@/lib/api'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import { FairnessChart } from '@/components/FairnessChart'
import { ScheduleGrid } from '@/components/ScheduleGrid'
import { RequestCard } from '@/components/RequestCard'
import { EmployeeCard } from '@/components/EmployeeCard'
import { AIChat } from '@/components/AIChat'
import { useToast } from '@/hooks/useToast'
import { Calendar, CheckCircle2, Send, Sparkles, Users } from 'lucide-react'

// Returns the ISO date string for the Monday of the week containing dateString.
function startOfWeekIso(dateString: string) {
  const date = new Date(`${dateString}T00:00:00`)
  const day = date.getDay()
  const distanceFromMonday = (day + 6) % 7
  date.setDate(date.getDate() - distanceFromMonday)
  const year = date.getFullYear()
  const month = String(date.getMonth() + 1).padStart(2, '0')
  const dayOfMonth = String(date.getDate()).padStart(2, '0')
  return `${year}-${month}-${dayOfMonth}`
}

// Formats a Date as YYYY-MM-DD in local time.
function localIsoDate(date: Date) {
  const year = date.getFullYear()
  const month = String(date.getMonth() + 1).padStart(2, '0')
  const dayOfMonth = String(date.getDate()).padStart(2, '0')
  return `${year}-${month}-${dayOfMonth}`
}

function todayStartOfWeekIso() {
  return startOfWeekIso(localIsoDate(new Date()))
}

export function OwnerDashboard() {
  const queryClient = useQueryClient()
  const { toast } = useToast()
  const [currentScheduleRunId, setCurrentScheduleRunId] = useState<number | null>(null)
  const [redoReason, setRedoReason] = useState('')
  const [showChat, setShowChat] = useState(false)

  const employeesQuery = useQuery({
    queryKey: ['employees'],
    queryFn: () => apiClient.getEmployees(),
  })

  const requestsQuery = useQuery({
    queryKey: ['time-off-requests'],
    queryFn: () => apiClient.listTimeOffRequests(),
  })

  const shiftsQuery = useQuery({
    queryKey: ['shifts'],
    queryFn: () => apiClient.getShifts(),
  })

  const latestDraftRunQuery = useQuery({
    queryKey: ['latest-schedule-run', 'draft'],
    queryFn: async () => {
      try {
        return await apiClient.getLatestScheduleRun('draft')
      } catch (err) {
        if (err instanceof ApiError && err.status === 404) {
          return null
        }
        throw err
      }
    },
    retry: false,
  })

  const latestPublishedRunQuery = useQuery({
    queryKey: ['latest-schedule-run', 'published'],
    queryFn: () => apiClient.getLatestScheduleRun('published'),
    retry: false,
  })

  const activeScheduleRunId =
    currentScheduleRunId ??
    latestDraftRunQuery.data?.schedule_run_id ??
    latestPublishedRunQuery.data?.schedule_run_id ??
    null

  const scheduleRunQuery = useQuery({
    queryKey: ['schedule-run', activeScheduleRunId],
    queryFn: () => apiClient.getScheduleRun(activeScheduleRunId as number),
    enabled: activeScheduleRunId !== null,
  })

  const fairnessQuery = useQuery({
    queryKey: ['fairness-charts', activeScheduleRunId],
    queryFn: () => apiClient.getFairnessCharts(activeScheduleRunId as number),
    enabled: activeScheduleRunId !== null,
  })

  const metricsQuery = useQuery({
    queryKey: ['schedule-metrics', activeScheduleRunId],
    queryFn: () => apiClient.getScheduleMetrics(activeScheduleRunId as number),
    enabled: activeScheduleRunId !== null,
  })

  const aiKpisQuery = useQuery({
    queryKey: ['ai-kpis', 30],
    queryFn: () => apiClient.getAIKpis(30),
    enabled: showChat,
  })

  const employeeNameById = useMemo(() => {
    const employees = employeesQuery.data ?? []
    return Object.fromEntries(employees.map((employee) => [employee.id, employee.name]))
  }, [employeesQuery.data])

  const fairnessByEmployeeId = useMemo(() => {
    const fairnessScores = scheduleRunQuery.data?.schedule.fairness_scores ?? []
    return Object.fromEntries(fairnessScores.map((score) => [score.employee_id, score.percentage]))
  }, [scheduleRunQuery.data])

  const pendingRequests = useMemo(
    () => (requestsQuery.data ?? []).filter((request) => request.status === 'pending'),
    [requestsQuery.data],
  )

  const generateWeekStart = todayStartOfWeekIso()

  const generateMutation = useMutation({
    mutationFn: () => apiClient.generateSchedule(generateWeekStart),
    onSuccess: (response) => {
      setCurrentScheduleRunId(response.schedule_run_id)
      toast({
        title: 'Schedule generated',
        description: `Run #${response.schedule_run_id} created for week ${generateWeekStart}.`,
      })
      void queryClient.invalidateQueries({ queryKey: ['schedule-run', response.schedule_run_id] })
      void queryClient.invalidateQueries({ queryKey: ['schedule-metrics', response.schedule_run_id] })
      void queryClient.invalidateQueries({ queryKey: ['fairness-charts', response.schedule_run_id] })
    },
    onError: (err) => {
      toast({
        title: 'Generate failed',
        description: err instanceof Error ? err.message : 'Unable to generate schedule.',
        variant: 'error',
      })
    },
  })

  const publishMutation = useMutation({
    mutationFn: (scheduleRunId: number) => apiClient.publishSchedule(scheduleRunId),
    onSuccess: () => {
      toast({ title: 'Schedule published', description: 'Employees can now view this schedule.' })
      if (activeScheduleRunId !== null) {
        void queryClient.invalidateQueries({ queryKey: ['schedule-metrics', activeScheduleRunId] })
      }
    },
    onError: (err) => {
      toast({
        title: 'Publish failed',
        description: err instanceof Error ? err.message : 'Unable to publish schedule.',
        variant: 'error',
      })
    },
  })

  const redoMutation = useMutation({
    mutationFn: ({ scheduleRunId, reason }: { scheduleRunId: number; reason: string }) =>
      apiClient.redoSchedule(scheduleRunId, reason),
    onSuccess: (response) => {
      setCurrentScheduleRunId(response.schedule_run_id)
      setRedoReason('')
      toast({ title: 'Schedule redone', description: `New run #${response.schedule_run_id} created.` })
      void queryClient.invalidateQueries({ queryKey: ['schedule-run', response.schedule_run_id] })
      void queryClient.invalidateQueries({ queryKey: ['schedule-metrics', response.schedule_run_id] })
      void queryClient.invalidateQueries({ queryKey: ['fairness-charts', response.schedule_run_id] })
    },
    onError: (err) => {
      toast({
        title: 'Redo failed',
        description: err instanceof Error ? err.message : 'Unable to redo schedule.',
        variant: 'error',
      })
    },
  })

  const approveMutation = useMutation({
    mutationFn: (requestId: number) => apiClient.approveTimeOff(requestId),
    onSuccess: () => {
      toast({ title: 'Request approved' })
      void queryClient.invalidateQueries({ queryKey: ['time-off-requests'] })
    },
    onError: (err) => {
      toast({
        title: 'Approve failed',
        description: err instanceof Error ? err.message : 'Unable to approve request.',
        variant: 'error',
      })
    },
  })

  const denyMutation = useMutation({
    mutationFn: (requestId: number) => apiClient.denyTimeOff(requestId),
    onSuccess: () => {
      toast({ title: 'Request denied' })
      void queryClient.invalidateQueries({ queryKey: ['time-off-requests'] })
    },
    onError: (err) => {
      toast({
        title: 'Deny failed',
        description: err instanceof Error ? err.message : 'Unable to deny request.',
        variant: 'error',
      })
    },
  })

  const isLoading = employeesQuery.isLoading || requestsQuery.isLoading || shiftsQuery.isLoading

  if (isLoading) {
    return <div className="text-sm text-muted-foreground">Loading dashboard data...</div>
  }

  if (employeesQuery.isError || requestsQuery.isError || shiftsQuery.isError) {
    const err = employeesQuery.error || requestsQuery.error || shiftsQuery.error
    if (err instanceof ApiError && err.status === 403) {
      return <div className="text-sm text-destructive">You do not have permission to access owner dashboard data.</div>
    }
    return <div className="text-sm text-destructive">Failed to load dashboard data. Please refresh and try again.</div>
  }

  const employees = employeesQuery.data ?? []
  const shifts = shiftsQuery.data ?? []
  const averageFairness = metricsQuery.data?.overall_fairness_percent ?? null

  return (
    <div className="space-y-8">
      <header className="flex flex-wrap items-center justify-between gap-4 rounded-2xl border border-border/65 bg-gradient-hero p-5">
        <div>
          <p className="text-xs font-semibold uppercase tracking-[0.16em] text-muted-foreground">Owner dashboard</p>
          <h1 className="mt-1 text-3xl font-bold tracking-tight">Operations Command Center</h1>
          <p className="mt-1 text-sm text-muted-foreground">Generate, publish, review requests, and keep fairness visible.</p>
        </div>
        <Button onClick={() => setShowChat((prev) => !prev)} size="sm" variant="gradient">
          <Sparkles className="h-4 w-4" />
          {showChat ? 'Hide AI panel' : 'Open AI panel'}
        </Button>
      </header>

      <div className="grid gap-4 md:grid-cols-4">
        <StatCard icon={<Users className="h-4 w-4" />} label="Employees" value={String(employees.length)} />
        <StatCard icon={<Calendar className="h-4 w-4" />} label="Pending Requests" value={String(pendingRequests.length)} />
        <StatCard
          icon={<CheckCircle2 className="h-4 w-4" />}
          label="Schedule Status"
          value={(metricsQuery.data?.status ?? 'not generated').toUpperCase()}
        />
        <StatCard
          icon={<Sparkles className="h-4 w-4" />}
          label="Average Fairness"
          value={averageFairness === null ? 'N/A' : `${Math.round(averageFairness)}%`}
        />
      </div>

      <div className={`grid gap-8 ${showChat ? 'xl:grid-cols-[2fr_1fr]' : ''}`}>
        <div className="space-y-8">
          <Card className="border-primary/20">
            <CardHeader>
              <CardTitle className="text-lg">Schedule Actions</CardTitle>
            </CardHeader>
            <CardContent className="space-y-4">
              <p className="text-sm text-muted-foreground">
                Target week start: <span className="font-semibold text-foreground">{generateWeekStart}</span>
              </p>
              <div className="flex flex-wrap gap-2">
                <Button disabled={generateMutation.isPending} onClick={() => generateMutation.mutate()} variant="gradient">
                  Generate
                </Button>
                <Button
                  disabled={activeScheduleRunId === null || publishMutation.isPending}
                  onClick={() => activeScheduleRunId !== null && publishMutation.mutate(activeScheduleRunId)}
                  variant="outline"
                >
                  <Send className="h-4 w-4" />
                  Publish
                </Button>
              </div>
              <div className="flex flex-col gap-2 sm:flex-row">
                <Input onChange={(event) => setRedoReason(event.target.value)} placeholder="Why regenerate schedule?" value={redoReason} />
                <Button
                  disabled={activeScheduleRunId === null || redoReason.trim().length === 0 || redoMutation.isPending}
                  onClick={() =>
                    activeScheduleRunId !== null &&
                    redoMutation.mutate({ reason: redoReason.trim(), scheduleRunId: activeScheduleRunId })
                  }
                  variant="outline"
                >
                  Regenerate
                </Button>
              </div>
              {activeScheduleRunId !== null ? (
                <p className="text-xs text-muted-foreground">Current run ID: {activeScheduleRunId}</p>
              ) : null}
            </CardContent>
          </Card>

          {scheduleRunQuery.data ? (
            <ScheduleGrid employeeNameById={employeeNameById} scheduleRun={scheduleRunQuery.data} shifts={shifts} />
          ) : (
            <Card>
              <CardHeader>
                <CardTitle>Schedule Preview</CardTitle>
              </CardHeader>
              <CardContent className="text-sm text-muted-foreground">Generate a schedule to preview assignments.</CardContent>
            </Card>
          )}

          {fairnessQuery.data ? <FairnessChart data={fairnessQuery.data} employeeNameById={employeeNameById} /> : null}

          <section className="space-y-4">
            <div className="flex items-center justify-between">
              <h2 className="text-xl font-bold text-foreground">Pending Requests</h2>
              <span className="text-sm text-muted-foreground">{pendingRequests.length} pending</span>
            </div>
            {pendingRequests.length === 0 ? (
              <p className="text-sm text-muted-foreground">No pending requests right now.</p>
            ) : (
              <div className="grid gap-3 md:grid-cols-2">
                {pendingRequests.map((request) => (
                  <RequestCard
                    employeeName={employeeNameById[request.employee_id] ?? request.employee_id}
                    isBusy={approveMutation.isPending || denyMutation.isPending}
                    key={request.id}
                    onApprove={() => approveMutation.mutate(request.id)}
                    onDeny={() => denyMutation.mutate(request.id)}
                    request={request}
                  />
                ))}
              </div>
            )}
          </section>

          <section className="space-y-4">
            <div className="flex items-center justify-between">
              <h2 className="text-xl font-bold text-foreground">Team Members</h2>
              <span className="text-sm text-muted-foreground">{employees.length} employees</span>
            </div>
            <div className="grid gap-3 md:grid-cols-2">
              {employees.map((employee) => (
                <EmployeeCard employee={employee} fairnessPercent={fairnessByEmployeeId[employee.id] ?? null} key={employee.id} />
              ))}
            </div>
          </section>
        </div>

        {showChat ? (
          <div className="sticky top-24 h-fit">
            {aiKpisQuery.data ? (
              <Card className="mb-4 border-primary/20">
                <CardHeader>
                  <CardTitle className="text-base">AI Metrics (30d)</CardTitle>
                </CardHeader>
                <CardContent className="grid grid-cols-2 gap-2 text-xs text-muted-foreground">
                  <p>Suggestions: {aiKpisQuery.data.suggestions}</p>
                  <p>Confirmed: {aiKpisQuery.data.confirmed_actions}</p>
                  <p>Fairness delta: {aiKpisQuery.data.fairness_delta_avg.toFixed(2)}</p>
                  <p>Request accept: {aiKpisQuery.data.request_acceptance_rate_percent.toFixed(1)}%</p>
                </CardContent>
              </Card>
            ) : null}
            <AIChat
              onActionExecuted={() => {
                void queryClient.invalidateQueries({ queryKey: ['time-off-requests'] })
                void queryClient.invalidateQueries({ queryKey: ['latest-schedule-run'] })
                void queryClient.invalidateQueries({ queryKey: ['schedule-run'] })
                void queryClient.invalidateQueries({ queryKey: ['schedule-metrics'] })
                void queryClient.invalidateQueries({ queryKey: ['fairness-charts'] })
                void queryClient.invalidateQueries({ queryKey: ['ai-kpis'] })
              }}
              scheduleRunId={activeScheduleRunId}
            />
          </div>
        ) : null}
      </div>
    </div>
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
