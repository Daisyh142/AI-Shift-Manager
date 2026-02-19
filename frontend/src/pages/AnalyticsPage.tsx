import { useMemo } from 'react'
import { useQuery } from '@tanstack/react-query'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { apiClient } from '@/lib/api'
import { AlertTriangle, BarChart3, ShieldCheck, Sparkles } from 'lucide-react'

export function AnalyticsPage() {
  const latestPublishedRunQuery = useQuery({
    queryKey: ['latest-schedule-run', 'published'],
    queryFn: () => apiClient.getLatestScheduleRun('published'),
  })

  const metricsQuery = useQuery({
    queryKey: ['schedule-metrics', latestPublishedRunQuery.data?.schedule_run_id],
    queryFn: () => apiClient.getScheduleMetrics(latestPublishedRunQuery.data!.schedule_run_id),
    enabled: Boolean(latestPublishedRunQuery.data?.schedule_run_id),
  })

  const employeesQuery = useQuery({
    queryKey: ['employees'],
    queryFn: () => apiClient.getEmployees(),
  })

  const fairnessByEmployee = useMemo(() => metricsQuery.data?.employee_fairness ?? [], [metricsQuery.data])
  const employeeNameById = useMemo(
    () => Object.fromEntries((employeesQuery.data ?? []).map((employee) => [employee.id, employee.name])),
    [employeesQuery.data],
  )

  if (latestPublishedRunQuery.isLoading || metricsQuery.isLoading) {
    return <div className="text-sm text-muted-foreground">Loading analytics...</div>
  }

  if (!latestPublishedRunQuery.data || !metricsQuery.data) {
    return <div className="text-sm text-muted-foreground">Publish a schedule to see analytics.</div>
  }

  return (
    <section className="space-y-6">
      <header className="space-y-2 rounded-2xl border border-border/65 bg-gradient-hero p-5">
        <p className="text-xs font-semibold uppercase tracking-[0.16em] text-muted-foreground">Analytics</p>
        <h1 className="text-3xl font-bold tracking-tight">Coverage and Fairness Insights</h1>
        <p className="text-sm text-muted-foreground">Metrics from published schedule run #{latestPublishedRunQuery.data.schedule_run_id}.</p>
      </header>

      <div className="grid gap-4 md:grid-cols-3">
        <Card className="border-primary/20">
          <CardHeader className="pb-2">
            <CardTitle className="text-sm font-semibold text-muted-foreground">Coverage</CardTitle>
          </CardHeader>
          <CardContent>
            <div className="mb-2 flex items-center gap-2 text-primary">
              <BarChart3 className="h-4 w-4" />
              <span className="text-3xl font-bold">{metricsQuery.data.coverage_percent.toFixed(1)}%</span>
            </div>
          </CardContent>
        </Card>
        <Card className="border-primary/20">
          <CardHeader className="pb-2">
            <CardTitle className="text-sm font-semibold text-muted-foreground">Overall Fairness</CardTitle>
          </CardHeader>
          <CardContent>
            <div className="mb-2 flex items-center gap-2 text-[color:var(--success)]">
              <ShieldCheck className="h-4 w-4" />
              <span className="text-3xl font-bold">{Math.round(metricsQuery.data.overall_fairness_percent)}%</span>
            </div>
          </CardContent>
        </Card>
        <Card className="border-primary/20">
          <CardHeader className="pb-2">
            <CardTitle className="text-sm font-semibold text-muted-foreground">Understaffed Shifts</CardTitle>
          </CardHeader>
          <CardContent>
            <div className="mb-2 flex items-center gap-2 text-[color:var(--warning)]">
              <AlertTriangle className="h-4 w-4" />
              <span className="text-3xl font-bold">{metricsQuery.data.understaffed_shifts}</span>
            </div>
          </CardContent>
        </Card>
      </div>

      <Card className="border-primary/15">
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <Sparkles className="h-4 w-4 text-primary" />
            Employee Fairness Breakdown
          </CardTitle>
        </CardHeader>
        <CardContent className="space-y-3">
          {fairnessByEmployee.map((score) => (
            <div className="space-y-1 rounded-xl bg-muted/35 p-3" key={score.employee_id}>
              <div className="flex items-center justify-between text-sm">
                <span className="font-medium text-foreground">{employeeNameById[score.employee_id] ?? score.employee_id}</span>
                <span className="text-muted-foreground">{score.percentage.toFixed(1)}%</span>
              </div>
              <div className="h-2 rounded-full bg-border/70">
                <div className="h-2 rounded-full bg-primary" style={{ width: `${score.percentage}%` }} />
              </div>
            </div>
          ))}
        </CardContent>
      </Card>
    </section>
  )
}
