import { useMemo, useState, type ReactNode } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { ApiError, apiClient } from '@/lib/api'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { FairnessChart } from '@/components/FairnessChart'
import { ScheduleGrid } from '@/components/ScheduleGrid'
import { RequestCard } from '@/components/RequestCard'
import { EmployeeCard } from '@/components/EmployeeCard'
import { AIChat } from '@/components/AIChat'
import { useToast } from '@/hooks/useToast'
import { Calendar, CheckCircle2, Send, Sparkles, Users } from 'lucide-react'

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

function localIsoDate(date: Date) {
  const year = date.getFullYear()
  const month = String(date.getMonth() + 1).padStart(2, '0')
  const dayOfMonth = String(date.getDate()).padStart(2, '0')
  return `${year}-${month}-${dayOfMonth}`
}

function todayStartOfWeekIso() {
  return startOfWeekIso(localIsoDate(new Date()))
}

function collectTwoWeekShiftDebug(weekStartDate: string, shifts: { date: string; start_time: string; end_time: string }[]) {
  const start = new Date(`${weekStartDate}T00:00:00`)
  const end = new Date(start)
  end.setDate(start.getDate() + 13)
  const periodShifts = shifts.filter((shift) => {
    const shiftDate = new Date(`${shift.date}T00:00:00`)
    return shiftDate >= start && shiftDate <= end
  })
  const uniqueStartTimes = new Set(periodShifts.map((shift) => shift.start_time))
  const uniqueStartEndPairs = new Set(periodShifts.map((shift) => `${shift.start_time}-${shift.end_time}`))
  return {
    shiftCount: periodShifts.length,
    uniqueStartTimesCount: uniqueStartTimes.size,
    uniqueStartEndPairsCount: uniqueStartEndPairs.size,
    uniqueStartTimes: Array.from(uniqueStartTimes).sort(),
    uniqueStartEndPairs: Array.from(uniqueStartEndPairs).sort(),
  }
}

export function OwnerDashboard() {
  const queryClient = useQueryClient()
  const { toast } = useToast()
  const [currentScheduleRunId, setCurrentScheduleRunId] = useState<number | null>(null)
  const [coverEmployeeByRequestId, setCoverEmployeeByRequestId] = useState<Record<number, string>>({})

  const employeesQuery = useQuery({
    queryKey: ['employees'],
    queryFn: () => apiClient.getEmployees(),
  })

  const requestsQuery = useQuery({
    queryKey: ['time-off-requests'],
    queryFn: () => apiClient.listTimeOffRequests(),
  })
  const pendingCoverageQuery = useQuery({
    queryKey: ['pending-coverage-requests'],
    queryFn: () => apiClient.listPendingCoverageRequests(),
  })
  const pendingHoursQuery = useQuery({
    queryKey: ['pending-hours-requests'],
    queryFn: () => apiClient.listPendingHoursRequests(),
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
  const pendingCoverageRequests = pendingCoverageQuery.data ?? []
  const pendingHoursRequests = pendingHoursQuery.data ?? []

  const generateWeekStart = todayStartOfWeekIso()

  const refreshScheduleQueries = async (scheduleRunId: number) => {
    await Promise.all([
      queryClient.invalidateQueries({ queryKey: ['employees'] }),
      queryClient.invalidateQueries({ queryKey: ['latest-schedule-run', 'draft'] }),
      queryClient.invalidateQueries({ queryKey: ['latest-schedule-run', 'published'] }),
      queryClient.invalidateQueries({ queryKey: ['schedule-run', scheduleRunId] }),
      queryClient.invalidateQueries({ queryKey: ['schedule-metrics', scheduleRunId] }),
      queryClient.invalidateQueries({ queryKey: ['fairness-charts', scheduleRunId] }),
      queryClient.invalidateQueries({ queryKey: ['shifts'] }),
    ])
  }

  const logShiftDebugForRun = async (scheduleRunId: number) => {
    const [runResponse, shifts] = await Promise.all([
      queryClient.fetchQuery({
        queryKey: ['schedule-run', scheduleRunId],
        queryFn: () => apiClient.getScheduleRun(scheduleRunId),
      }),
      queryClient.fetchQuery({
        queryKey: ['shifts'],
        queryFn: () => apiClient.getShifts(),
      }),
    ])
    const debug = collectTwoWeekShiftDebug(runResponse.schedule.week_start_date, shifts)
    console.info('[OwnerDashboard] Generated schedule shift debug', {
      scheduleRunId,
      ...debug,
    })
    if (debug.uniqueStartTimesCount <= 2) {
      console.warn('[OwnerDashboard] Shift start times look rigid', {
        scheduleRunId,
        ...debug,
      })
    }
  }

  const generateMutation = useMutation({
    mutationFn: () => apiClient.generateSchedule(generateWeekStart),
    onSuccess: async (response) => {
      queryClient.setQueryData(['schedule-run', response.schedule_run_id], response)

      await queryClient.fetchQuery({
        queryKey: ['shifts'],
        queryFn: () => apiClient.getShifts(),
      })

      setCurrentScheduleRunId(response.schedule_run_id)

      toast({
        title: 'Schedule generated',
        description:
          response.ai_summary ??
          `Run #${response.schedule_run_id} created for week ${generateWeekStart}.`,
      })

      await refreshScheduleQueries(response.schedule_run_id)
      await logShiftDebugForRun(response.schedule_run_id)
    },
    onError: (err) => {
      console.error('Generate schedule failed', err)
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
      console.error('Publish schedule failed', err)
      toast({
        title: 'Publish failed',
        description: err instanceof Error ? err.message : 'Unable to publish schedule.',
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
      console.error('Approve request failed', err)
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
      console.error('Deny request failed', err)
      toast({
        title: 'Deny failed',
        description: err instanceof Error ? err.message : 'Unable to deny request.',
        variant: 'error',
      })
    },
  })

  const coverageDecisionMutation = useMutation({
    mutationFn: ({
      requestId,
      decision,
      coverEmployeeId,
    }: {
      requestId: number
      decision: 'approved' | 'denied'
      coverEmployeeId?: string | null
    }) =>
      apiClient.decideCoverageRequest(requestId, {
        decision,
        cover_employee_id: coverEmployeeId ?? null,
      }),
    onSuccess: () => {
      toast({ title: 'Coverage request updated' })
      void queryClient.invalidateQueries({ queryKey: ['pending-coverage-requests'] })
      void queryClient.invalidateQueries({ queryKey: ['my-coverage-requests'] })
    },
    onError: (err) => {
      console.error('Coverage decision failed', err)
      toast({
        title: 'Coverage decision failed',
        description: err instanceof Error ? err.message : 'Unable to update coverage request.',
        variant: 'error',
      })
    },
  })

  const hoursDecisionMutation = useMutation({
    mutationFn: ({ requestId, decision }: { requestId: number; decision: 'approved' | 'denied' }) =>
      apiClient.decideHoursRequest(requestId, { decision }),
    onSuccess: () => {
      toast({ title: 'Hours request updated' })
      void queryClient.invalidateQueries({ queryKey: ['pending-hours-requests'] })
      void queryClient.invalidateQueries({ queryKey: ['my-hours-requests'] })
    },
    onError: (err) => {
      console.error('Hours decision failed', err)
      toast({
        title: 'Hours decision failed',
        description: err instanceof Error ? err.message : 'Unable to update hours request.',
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
      <header className="rounded-2xl border border-border/65 bg-gradient-hero p-5">
        <p className="text-xs font-semibold uppercase tracking-[0.16em] text-muted-foreground">Owner dashboard</p>
        <h1 className="mt-1 text-3xl font-bold tracking-tight">Operations Command Center</h1>
        <p className="mt-1 text-sm text-muted-foreground">Use the AI assistant below to generate, publish, and manage schedules. Review requests and fairness.</p>
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

      <div className="space-y-8">
        <div className="flex flex-col gap-3 rounded-xl border border-border/60 bg-muted/30 p-3 sm:flex-row sm:flex-wrap sm:items-center">
          <span className="text-sm text-muted-foreground">
            Pay Period: <span className="font-semibold text-foreground">{generateWeekStart}</span>
            {activeScheduleRunId !== null ? ` · Run #${activeScheduleRunId}` : null}
          </span>
          <div className="flex flex-wrap items-center gap-2">
            <Button disabled={generateMutation.isPending} onClick={() => generateMutation.mutate()} size="sm" variant="gradient">
              Generate
            </Button>
            <Button
              disabled={activeScheduleRunId === null || publishMutation.isPending}
              onClick={() => activeScheduleRunId !== null && publishMutation.mutate(activeScheduleRunId)}
              size="sm"
              variant="outline"
            >
              <Send className="h-4 w-4" />
              Publish
            </Button>
          </div>
        </div>

        {aiKpisQuery.data ? (
          <div className="flex flex-wrap gap-4 rounded-xl border border-primary/20 bg-primary/5 px-4 py-2 text-xs text-muted-foreground">
            <span>Suggestions: {aiKpisQuery.data.suggestions}</span>
            <span>Confirmed: {aiKpisQuery.data.confirmed_actions}</span>
            <span>Fairness Δ: {aiKpisQuery.data.fairness_delta_avg.toFixed(2)}</span>
            <span>Request accept: {aiKpisQuery.data.request_acceptance_rate_percent.toFixed(1)}%</span>
          </div>
        ) : null}

        <AIChat
          onActionExecuted={() => {
            void queryClient.invalidateQueries({ queryKey: ['time-off-requests'] })
            void queryClient.invalidateQueries({ queryKey: ['latest-schedule-run', 'draft'] })
            void queryClient.invalidateQueries({ queryKey: ['latest-schedule-run', 'published'] })
            void queryClient.invalidateQueries({ queryKey: ['schedule-run'] })
            void queryClient.invalidateQueries({ queryKey: ['schedule-metrics'] })
            void queryClient.invalidateQueries({ queryKey: ['fairness-charts'] })
            void queryClient.invalidateQueries({ queryKey: ['shifts'] })
            void queryClient.invalidateQueries({ queryKey: ['ai-kpis'] })
          }}
          onScheduleRegenerated={async (runId) => {
            await queryClient.fetchQuery({
              queryKey: ['shifts'],
              queryFn: () => apiClient.getShifts(),
            })
            setCurrentScheduleRunId(runId)
            void refreshScheduleQueries(runId)
            void logShiftDebugForRun(runId)
            void queryClient.invalidateQueries({ queryKey: ['ai-kpis'] })
          }}
          scheduleRunId={activeScheduleRunId}
        />

        {generateMutation.isPending ? (
            <Card>
              <CardHeader>
                <CardTitle>Schedule Preview</CardTitle>
              </CardHeader>
              <CardContent className="space-y-3 p-4">
                <p className="text-sm text-muted-foreground animate-pulse">Generating schedule — analyzing shifts and availability…</p>
                {[1, 2, 3].map((i) => (
                  <div className="h-10 w-full animate-pulse rounded-lg bg-muted" key={i} />
                ))}
              </CardContent>
            </Card>
          ) : scheduleRunQuery.data ? (
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
              <h2 className="text-xl font-bold text-foreground">Coverage Requests</h2>
              <span className="text-sm text-muted-foreground">{pendingCoverageRequests.length} pending</span>
            </div>
            {pendingCoverageRequests.length === 0 ? (
              <p className="text-sm text-muted-foreground">No pending coverage requests right now.</p>
            ) : (
              <div className="grid gap-3 md:grid-cols-2">
                {pendingCoverageRequests.map((request) => {
                  const selectedCoverEmployee = coverEmployeeByRequestId[request.id] ?? ''
                  return (
                    <Card className="border-border/70" key={request.id}>
                      <CardContent className="space-y-2 p-4 text-sm">
                        <p className="font-semibold">Shift #{request.shift_id}</p>
                        <p className="text-muted-foreground">
                          Requester: {employeeNameById[request.requester_employee_id] ?? request.requester_employee_id}
                        </p>
                        {request.reason ? <p className="text-muted-foreground">Reason: {request.reason}</p> : null}
                        <label className="block text-xs text-muted-foreground">
                          Optional cover employee
                          <select
                            className="mt-1 h-9 w-full rounded-[12px] border border-input bg-background/90 px-3 text-sm text-foreground transition-all focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
                            onChange={(event) =>
                              setCoverEmployeeByRequestId((prev) => ({ ...prev, [request.id]: event.target.value }))
                            }
                            value={selectedCoverEmployee}
                          >
                            <option value="">No specific cover</option>
                            {employees.map((employee) => (
                              <option key={employee.id} value={employee.id}>
                                {employee.name}
                              </option>
                            ))}
                          </select>
                        </label>
                        <div className="flex gap-2">
                          <Button
                            disabled={coverageDecisionMutation.isPending}
                            onClick={() =>
                              coverageDecisionMutation.mutate({
                                requestId: request.id,
                                decision: 'approved',
                                coverEmployeeId: selectedCoverEmployee || null,
                              })
                            }
                            size="sm"
                            variant="success"
                          >
                            Approve
                          </Button>
                          <Button
                            disabled={coverageDecisionMutation.isPending}
                            onClick={() =>
                              coverageDecisionMutation.mutate({
                                requestId: request.id,
                                decision: 'denied',
                                coverEmployeeId: null,
                              })
                            }
                            size="sm"
                            variant="outline"
                          >
                            Deny
                          </Button>
                        </div>
                      </CardContent>
                    </Card>
                  )
                })}
              </div>
            )}
          </section>

          <section className="space-y-4">
            <div className="flex items-center justify-between">
              <h2 className="text-xl font-bold text-foreground">Hours Change Requests</h2>
              <span className="text-sm text-muted-foreground">{pendingHoursRequests.length} pending</span>
            </div>
            {pendingHoursRequests.length === 0 ? (
              <p className="text-sm text-muted-foreground">No pending hours requests right now.</p>
            ) : (
              <div className="grid gap-3 md:grid-cols-2">
                {pendingHoursRequests.map((request) => (
                  <Card className="border-border/70" key={request.id}>
                    <CardContent className="space-y-2 p-4 text-sm">
                      <p className="font-semibold">{employeeNameById[request.employee_id] ?? request.employee_id}</p>
                      <p className="text-muted-foreground">
                        Period: {request.period_start} to {request.period_end}
                      </p>
                      <p className="text-muted-foreground">Requested hours: {request.requested_hours}</p>
                      {request.note ? <p className="text-muted-foreground">Note: {request.note}</p> : null}
                      <div className="flex gap-2">
                        <Button
                          disabled={hoursDecisionMutation.isPending}
                          onClick={() =>
                            hoursDecisionMutation.mutate({
                              requestId: request.id,
                              decision: 'approved',
                            })
                          }
                          size="sm"
                          variant="success"
                        >
                          Approve
                        </Button>
                        <Button
                          disabled={hoursDecisionMutation.isPending}
                          onClick={() =>
                            hoursDecisionMutation.mutate({
                              requestId: request.id,
                              decision: 'denied',
                            })
                          }
                          size="sm"
                          variant="outline"
                        >
                          Deny
                        </Button>
                      </div>
                    </CardContent>
                  </Card>
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
