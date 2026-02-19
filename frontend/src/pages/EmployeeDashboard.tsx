import { useMemo, type ReactNode } from 'react'
import { useQuery } from '@tanstack/react-query'
import { Link } from 'wouter'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { useAuth } from '@/hooks/useAuth'
import { apiClient } from '@/lib/api'
import { ScheduleGrid } from '@/components/ScheduleGrid'
import { TeamScheduleView } from '@/components/TeamScheduleView'
import { Button } from '@/components/ui/button'
import { Calendar, Clock, Users } from 'lucide-react'

export function EmployeeDashboard() {
  const { user } = useAuth()
  const employeeId = user?.employee_id

  const employeeQuery = useQuery({
    queryKey: ['employee', employeeId],
    queryFn: () => apiClient.getEmployee(employeeId as string),
    enabled: Boolean(employeeId),
  })

  const requestsQuery = useQuery({
    queryKey: ['time-off-requests'],
    queryFn: () => apiClient.listTimeOffRequests(),
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
        <Button className="w-full justify-start" disabled variant="outline">
          Coverage requests (coming next)
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
    </section>
  )
}

// Small stat tile shown in the employee header row.
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
