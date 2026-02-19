import { useQuery } from '@tanstack/react-query'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { TeamScheduleView } from '@/components/TeamScheduleView'
import { ApiError, apiClient } from '@/lib/api'
import { useAuth } from '@/hooks/useAuth'

export function AllSchedules() {
  const { user } = useAuth()

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

  if (employeesQuery.isLoading || shiftsQuery.isLoading || latestPublishedRunQuery.isLoading) {
    return <div className="text-sm text-muted-foreground">Loading team schedule...</div>
  }

  if (employeesQuery.isError || shiftsQuery.isError) {
    return <div className="text-sm text-destructive">Failed to load schedule data. Please refresh.</div>
  }

  if (latestPublishedRunQuery.isError) {
    const error = latestPublishedRunQuery.error
    if (error instanceof ApiError && error.status === 404) {
      return (
        <Card>
          <CardHeader>
            <CardTitle>Team Schedule</CardTitle>
          </CardHeader>
          <CardContent className="text-sm text-muted-foreground">
            No published schedule is available yet.
          </CardContent>
        </Card>
      )
    }
    return (
      <Card>
        <CardHeader>
          <CardTitle>Team Schedule</CardTitle>
        </CardHeader>
        <CardContent className="text-sm text-destructive">
          Unable to load latest published schedule.
        </CardContent>
      </Card>
    )
  }

  if (!latestPublishedRunQuery.data || !scheduleRunQuery.data) {
    return (
      <Card>
        <CardHeader>
          <CardTitle>Team Schedule</CardTitle>
        </CardHeader>
        <CardContent className="text-sm text-muted-foreground">
          No published schedule is available yet.
        </CardContent>
      </Card>
    )
  }

  return (
    <section className="space-y-4">
      <header className="space-y-2">
        <p className="text-xs font-semibold uppercase tracking-[0.16em] text-muted-foreground">Team schedule</p>
        <h1 className="text-3xl font-bold tracking-tight">Who You Are Working With</h1>
      </header>

      <Card className="border-primary/15 bg-gradient-to-br from-card to-primary/5">
        <CardHeader>
          <CardTitle className="text-lg">Current Published Schedule</CardTitle>
        </CardHeader>
        <CardContent className="text-sm text-muted-foreground">
          Week of {latestPublishedRunQuery.data.week_start_date}
        </CardContent>
      </Card>
      <TeamScheduleView
        assignments={scheduleRunQuery.data.schedule.assignments}
        currentEmployeeId={user?.employee_id ?? null}
        employees={employeesQuery.data ?? []}
        shifts={shiftsQuery.data ?? []}
        weekStartDate={latestPublishedRunQuery.data.week_start_date}
      />
    </section>
  )
}
