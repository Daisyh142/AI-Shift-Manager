import type { FairnessChartsResponse } from '@/lib/api'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { FairnessScore } from '@/components/FairnessScore'

interface FairnessChartProps {
  data: FairnessChartsResponse
  employeeNameById: Record<string, string>
}

// Keeps a percentage value within [0, 100].
function clampPercent(value: number) {
  return Math.max(0, Math.min(100, value))
}

// Resolves an employee ID to a display name, with a special case for the owner placeholder.
function displayEmployeeName(employeeId: string, employeeNameById: Record<string, string>) {
  if (employeeId.toLowerCase() === 'owner_id') return 'Owner'
  return employeeNameById[employeeId] ?? employeeId
}

export function FairnessChart({ data, employeeNameById }: FairnessChartProps) {
  const fairSlice = data.overall.find((slice) => slice.label === 'fair')
  const fairPercent = clampPercent(fairSlice?.value ?? 0)

  return (
    <Card className="border-primary/20">
      <CardHeader className="pb-2">
        <CardTitle className="text-lg">Fairness Overview</CardTitle>
      </CardHeader>
      <CardContent className="space-y-5">
        <div className="flex items-center gap-6 rounded-2xl bg-muted/50 p-4">
          <FairnessScore label="Average Fairness" score={fairPercent} size="md" />
          <div className="text-sm text-muted-foreground">
            Overall fairness from the current schedule run. Higher percentages indicate a more balanced distribution.
          </div>
        </div>
        <div className="space-y-3">
          {data.employees.map((slice) => {
            const employeeId = slice.label
            const percent = clampPercent(slice.value)
            return (
              <div key={employeeId} className="space-y-1 rounded-xl bg-muted/40 p-3">
                <div className="flex items-center justify-between text-sm">
                  <span className="font-medium">{displayEmployeeName(employeeId, employeeNameById)}</span>
                  <span className="text-muted-foreground">{percent.toFixed(1)}%</span>
                </div>
                <div className="h-2 rounded-full bg-border/70">
                  <div className="h-2 rounded-full bg-primary" style={{ width: `${percent}%` }} />
                </div>
              </div>
            )
          })}
        </div>
      </CardContent>
    </Card>
  )
}
