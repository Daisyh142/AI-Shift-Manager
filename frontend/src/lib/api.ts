const API_BASE_URL = import.meta.env.VITE_API_BASE_URL ?? 'http://localhost:8000'

let authToken: string | null = null
let authFailureHandler: (() => void) | null = null

export type UserRole = 'owner' | 'employee'

export interface AuthUser {
  id: number
  email: string
  role: UserRole
  employee_id: string | null
}

export interface TokenResponse {
  access_token: string
  token_type: 'bearer'
  user: AuthUser
}

export interface Employee {
  id: string
  name: string
  max_weekly_hours: number
  required_weekly_hours: number
  role: string
  employment_type: string
  pto_balance_hours: number
  category: string
}

export interface Shift {
  id: string
  date: string
  start_time: string
  end_time: string
  required_role: string | null
  required_staff: number
  required_category: string | null
}

export interface TimeOffRequestResponse {
  id: number
  employee_id: string
  date: string
  kind: 'pto' | 'request_off'
  status: 'pending' | 'approved' | 'denied'
  hours: number
  reason: string | null
  submitted_at: string | null
  decided_at: string | null
}

export interface FairnessScore {
  employee_id: string
  percentage: number
  reasoning: string[]
}

export interface Assignment {
  shift_id: string
  employee_id: string
}

export interface ScheduleResponse {
  week_start_date: string
  assignments: Assignment[]
  violations: string[]
  fairness_scores: FairnessScore[]
  overall_score: number | null
}

export interface ScheduleRunResponse {
  schedule_run_id: number
  schedule: ScheduleResponse
}

export interface ScheduleRunSummary {
  schedule_run_id: number
  week_start_date: string
  mode: string
  status: 'draft' | 'published'
  published_at: string | null
}

export interface FairnessChartSlice {
  label: string
  value: number
}

export interface FairnessChartsResponse {
  overall: FairnessChartSlice[]
  employees: FairnessChartSlice[]
}

export interface PublishScheduleResponse {
  schedule_run_id: number
  status: string
  published_at: string | null
}

export interface ScheduleMetricsResponse {
  schedule_run_id: number
  period_start_date: string
  period_days: number
  mode: string
  status: string
  total_shifts: number
  understaffed_shifts: number
  coverage_percent: number
  overall_fairness_percent: number
  employee_fairness: FairnessScore[]
  violations: string[]
}

export type AIRecommendationType =
  | 'recommend_time_off_decision'
  | 'analyze_coverage_conflicts'
  | 'explain_schedule_fairness'
  | 'propose_regeneration_parameters'

export type AIActionType =
  | 'redo_schedule'
  | 'approve_time_off'
  | 'deny_time_off'
  | 'remove_employee_and_regenerate'

export interface AIContextPointers {
  schedule_run_id?: number
  request_id?: number
  employee_id?: string
}

export interface AIChatRequest {
  message: string
  context?: AIContextPointers
  mode?: 'recommendation_only' | 'assistive'
}

export interface AIRecommendation {
  type: AIRecommendationType
  title: string
  rationale: string
  confidence: number
  fairness_impact?: string | null
  coverage_impact?: string | null
  constraint_rationale?: string | null
  suggested_params: Record<string, unknown>
}

export interface AIActionPayload {
  action_type: AIActionType
  label: string
  requires_confirmation: boolean
  params: Record<string, unknown>
}

export interface AIChatResponse {
  assistant_message: string
  recommendations: AIRecommendation[]
  action_payload?: AIActionPayload | null
  execution_mode: 'recommendation_only' | 'assistive'
}

export interface AIActionExecuteResponse {
  status: string
  message: string
  executed_endpoint?: string | null
  result?: Record<string, unknown> | null
}

export interface AIDecisionFeedbackRequest {
  action_type?: AIActionType
  recommendation_type?: AIRecommendationType
  decision: 'rejected' | 'suggested'
  schedule_run_id?: number
}

export interface AIKpiResponse {
  period_days: number
  suggestions: number
  confirmed_actions: number
  fairness_delta_avg: number
  request_acceptance_rate_percent: number
  conflict_resolution_success_rate_percent: number
}

// Typed error that carries the HTTP status code alongside the message.
export class ApiError extends Error {
  status: number

  constructor(message: string, status: number) {
    super(message)
    this.name = 'ApiError'
    this.status = status
  }
}

export function setAuthToken(token: string | null) {
  authToken = token
}

export function setAuthFailureHandler(handler: (() => void) | null) {
  authFailureHandler = handler
}

// Central fetch wrapper — attaches auth token, parses JSON, and throws ApiError on non-2xx responses.
async function apiFetch<T>(path: string, init: RequestInit = {}): Promise<T> {
  const headers = new Headers(init.headers)
  headers.set('Content-Type', 'application/json')
  if (authToken) {
    headers.set('Authorization', `Bearer ${authToken}`)
  }

  const response = await fetch(`${API_BASE_URL}${path}`, {
    ...init,
    headers,
  })

  const isJson = response.headers.get('content-type')?.includes('application/json')
  const body = isJson ? await response.json() : null

  if (!response.ok) {
    if (response.status === 401 && authFailureHandler) {
      authFailureHandler()
    }
    const detail = body?.detail
    const message =
      typeof detail === 'string'
        ? detail
        : typeof detail?.message === 'string'
          ? detail.message
          : 'Request failed'
    throw new ApiError(message, response.status)
  }

  return body as T
}

// All API calls go through this object so they share the same auth and base URL.
export const apiClient = {
  register(payload: { email: string; password: string; role?: UserRole }) {
    return apiFetch<TokenResponse>('/auth/register', {
      method: 'POST',
      body: JSON.stringify(payload),
    })
  },
  login(payload: { email: string; password: string }) {
    return apiFetch<TokenResponse>('/auth/login', {
      method: 'POST',
      body: JSON.stringify(payload),
    })
  },
  me() {
    return apiFetch<AuthUser>('/auth/me')
  },
  seedDemo() {
    return apiFetch<{ status: string }>('/seed', {
      method: 'POST',
    })
  },
  getEmployees() {
    return apiFetch<Employee[]>('/employees')
  },
  getShifts() {
    return apiFetch<Shift[]>('/shifts')
  },
  listTimeOffRequests() {
    return apiFetch<TimeOffRequestResponse[]>('/time-off/requests')
  },
  approveTimeOff(requestId: number) {
    return apiFetch<TimeOffRequestResponse>(`/time-off/requests/${requestId}/approve`, {
      method: 'POST',
    })
  },
  denyTimeOff(requestId: number) {
    return apiFetch<TimeOffRequestResponse>(`/time-off/requests/${requestId}/deny`, {
      method: 'POST',
    })
  },
  generateSchedule(weekStartDate?: string, mode: 'baseline' | 'optimized' = 'optimized') {
    return apiFetch<ScheduleRunResponse>(`/schedules/generate?mode=${mode}`, {
      method: 'POST',
      body: JSON.stringify(weekStartDate ? { week_start_date: weekStartDate } : {}),
    })
  },
  getScheduleRun(scheduleRunId: number) {
    return apiFetch<ScheduleRunResponse>(`/schedules/${scheduleRunId}`)
  },
  getLatestScheduleRun(status: 'draft' | 'published' = 'published') {
    return apiFetch<ScheduleRunSummary>(`/schedules/latest?status=${status}`)
  },
  getFairnessCharts(scheduleRunId: number) {
    return apiFetch<FairnessChartsResponse>(`/schedules/${scheduleRunId}/fairness-charts`)
  },
  publishSchedule(scheduleRunId: number) {
    return apiFetch<PublishScheduleResponse>(`/schedules/${scheduleRunId}/publish`, {
      method: 'POST',
    })
  },
  redoSchedule(scheduleRunId: number, reason: string) {
    return apiFetch<ScheduleRunResponse>(`/schedules/${scheduleRunId}/redo`, {
      method: 'POST',
      body: JSON.stringify({ reason }),
    })
  },
  getScheduleMetrics(scheduleRunId: number) {
    return apiFetch<ScheduleMetricsResponse>(`/metrics/schedules/${scheduleRunId}`)
  },
  getEmployee(employeeId: string) {
    return apiFetch<Employee>(`/employees/${employeeId}`)
  },
  createTimeOffRequest(payload: {
    employee_id: string
    date: string
    kind: 'pto' | 'request_off'
    hours?: number
    reason?: string
  }) {
    return apiFetch<TimeOffRequestResponse>('/time-off/requests', {
      method: 'POST',
      body: JSON.stringify(payload),
    })
  },
  chatAI(payload: AIChatRequest) {
    return apiFetch<AIChatResponse>('/ai/chat', {
      method: 'POST',
      body: JSON.stringify(payload),
    })
  },
  executeAIAction(action_payload: AIActionPayload) {
    return apiFetch<AIActionExecuteResponse>('/ai/execute-action', {
      method: 'POST',
      body: JSON.stringify({ action_payload }),
    })
  },
  getAIKpis(days = 30) {
    return apiFetch<AIKpiResponse>(`/ai/kpis?days=${days}`)
  },
  logAIFeedback(payload: AIDecisionFeedbackRequest) {
    return apiFetch<{ status: string }>('/ai/feedback', {
      method: 'POST',
      body: JSON.stringify(payload),
    })
  },
}
