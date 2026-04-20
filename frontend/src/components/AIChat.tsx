import { useEffect, useState } from 'react'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Sparkles } from 'lucide-react'
import { apiClient, type AIActionPayload, type AIRecommendation } from '@/lib/api'
import { ApiError } from '@/lib/api'
import { useToast } from '@/hooks/useToast'

interface Message {
  role: 'user' | 'assistant'
  content: string
  recommendations?: AIRecommendation[]
  actionPayload?: AIActionPayload | null
}

interface AIChatProps {
  scheduleRunId?: number | null
  onActionExecuted?: () => void
  onScheduleRegenerated?: (runId: number) => void
}

function isRegenerateIntent(message: string) {
  const normalized = message.trim().toLowerCase()
  return (
    normalized.startsWith('regenerate:') ||
    normalized.startsWith('redo:') ||
    normalized.includes('regenerate schedule')
  )
}

function toUnavailableLabel(category: string) {
  if (category === 'unauthorized') return 'AI unavailable (401 unauthorized)'
  if (category === 'missing_api_key') return 'AI unavailable (missing API key)'
  if (category === 'timeout') return 'AI unavailable (timeout)'
  return 'AI unavailable (server error)'
}

function categorizeFrontendError(err: unknown): string {
  if (err instanceof ApiError) {
    if (err.status === 401) return 'unauthorized'
    const normalized = err.message.toLowerCase()
    if (normalized.includes('api key') || normalized.includes('api_key')) return 'missing_api_key'
    if (normalized.includes('timeout') || normalized.includes('timed out')) return 'timeout'
    return 'server_error'
  }
  if (err instanceof Error) {
    const normalized = err.message.toLowerCase()
    if (normalized.includes('timeout') || normalized.includes('timed out')) return 'timeout'
  }
  return 'server_error'
}

export function AIChat({ scheduleRunId, onActionExecuted, onScheduleRegenerated }: AIChatProps) {
  const { toast } = useToast()
  const [input, setInput] = useState('')
  const [isSending, setIsSending] = useState(false)
  const [isExecutingAction, setIsExecutingAction] = useState<string | null>(null)
  const [pendingIntentToken, setPendingIntentToken] = useState<string | null>(null)
  const [dismissedActions, setDismissedActions] = useState<Record<string, true>>({})
  const [connectionState, setConnectionState] = useState<{
    checked: boolean
    connected: boolean
    provider?: string
    errorCode?: string | null
  }>({ checked: false, connected: false })
  const [messages, setMessages] = useState<Message[]>([
    {
      role: 'assistant',
      content:
        'Checking AI connection... Ask about fairness, coverage, or what to improve before regenerating a schedule.',
    },
  ])

  useEffect(() => {
    let mounted = true
    apiClient
      .getAIHealth()
      .then((health) => {
        if (!mounted) return
        setConnectionState({
          checked: true,
          connected: health.ok,
          provider: health.provider,
          errorCode: health.error_code ?? null,
        })
      })
      .catch((err) => {
        console.error('AI health check failed', err)
        if (!mounted) return
        setConnectionState({
          checked: true,
          connected: false,
          errorCode: categorizeFrontendError(err),
        })
      })
    return () => {
      mounted = false
    }
  }, [])

  async function sendMessage() {
    const trimmed = input.trim()
    if (!trimmed || isSending) return
    setMessages((prev) => [
      ...prev,
      { role: 'user', content: trimmed },
    ])
    setIsSending(true)
    setInput('')
    try {
      if (isRegenerateIntent(trimmed)) {
        if (!scheduleRunId) {
          setMessages((prev) => [
            ...prev,
            {
              role: 'assistant',
              content: 'Generate a schedule first, then ask me to regenerate it with a reason.',
            },
          ])
          return
        }

        const redoResponse = await apiClient.redoSchedule(scheduleRunId, trimmed)
        setMessages((prev) => [
          ...prev,
          {
            role: 'assistant',
            content: `I started regeneration using your reason: "${trimmed}". New run #${redoResponse.schedule_run_id} is ready.`,
          },
        ])
        onScheduleRegenerated?.(redoResponse.schedule_run_id)
        onActionExecuted?.()
        return
      }

      const response = await apiClient.chatAI({
        message: trimmed,
        context: scheduleRunId || pendingIntentToken
          ? {
              schedule_run_id: scheduleRunId ?? undefined,
              pending_intent_token: pendingIntentToken ?? undefined,
            }
          : undefined,
        mode: 'recommendation_only',
      })
      if (response.error_code) {
        console.error('AI chat returned provider error', response.error_code, response.assistant_message)
        const unavailableLabel = toUnavailableLabel(response.error_code)
        setMessages((prev) => [
          ...prev,
          {
            role: 'assistant',
            content: `${unavailableLabel}. ${response.assistant_message}`,
          },
        ])
        return
      }
      setMessages((prev) => [
        ...prev,
        {
          role: 'assistant',
          content: response.assistant_message,
          recommendations: response.recommendations,
          actionPayload: response.action_payload ?? null,
        },
      ])
      if (response.pending_intent_token) {
        setPendingIntentToken(response.pending_intent_token)
      } else if (response.new_schedule_run_id != null) {
        setPendingIntentToken(null)
      }
      if (response.new_schedule_run_id != null) {
        onScheduleRegenerated?.(response.new_schedule_run_id)
        onActionExecuted?.()
      }
    } catch (err) {
      console.error('AI chat request failed', err)
      const message =
        err instanceof ApiError
          ? `Unable to apply chat request right now: ${err.message}`
          : 'Unable to apply chat request right now. Please try again.'
      setMessages((prev) => [
        ...prev,
        {
          role: 'assistant',
          content: message,
        },
      ])
    } finally {
      setIsSending(false)
    }
  }

  async function confirmAction(actionPayload: AIActionPayload) {
    const actionKey = `${actionPayload.action_type}-${JSON.stringify(actionPayload.params)}`
    setIsExecutingAction(actionKey)
    try {
      await apiClient.executeAIAction(actionPayload)
      setDismissedActions((prev) => ({ ...prev, [actionKey]: true }))
      toast({
        title: 'AI action executed',
        description: 'The confirmed action was run through deterministic endpoints.',
      })
      onActionExecuted?.()
    } catch (err) {
      console.error('AI execute action failed', err)
      toast({
        title: 'Action failed',
        description: err instanceof Error ? err.message : 'Unable to execute confirmed action.',
        variant: 'error',
      })
    } finally {
      setIsExecutingAction(null)
    }
  }

  async function rejectAction(actionPayload: AIActionPayload) {
    const actionKey = `${actionPayload.action_type}-${JSON.stringify(actionPayload.params)}`
    setDismissedActions((prev) => ({ ...prev, [actionKey]: true }))
    try {
      await apiClient.logAIFeedback({
        action_type: actionPayload.action_type,
        decision: 'rejected',
        schedule_run_id: scheduleRunId ?? undefined,
      })
    } catch (err) {
      console.error('AI feedback logging failed', err)
    }
    toast({ title: 'Action skipped', description: 'No changes were applied.' })
  }

  return (
    <Card className="border-primary/15 flex flex-col">
      <CardHeader className="shrink-0">
        <CardTitle className="flex items-center gap-2 text-base">
          <Sparkles className="h-4 w-4 text-primary" />
          Shift Manager AI Assistant
        </CardTitle>
        <p className="text-xs text-muted-foreground">
          {!connectionState.checked
            ? 'Status: Checking connection...'
            : connectionState.connected
              ? `Status: Connected (${connectionState.provider ?? 'provider ready'})`
              : `Status: ${toUnavailableLabel(connectionState.errorCode ?? 'server_error')}`}
        </p>
      </CardHeader>
      <CardContent className="flex flex-col space-y-3">
        <div className="max-h-[200px] space-y-2 overflow-y-auto py-1 text-sm">
          {messages.map((message, index) => (
            <div className="space-y-1" key={`${message.role}-${index}`}>
              <p className="leading-relaxed">
                <span className="font-semibold capitalize">{message.role}:</span> {message.content}
              </p>
              {message.role === 'assistant' &&
              message.recommendations &&
              message.recommendations.length > 0 ? (
                <div className="space-y-2">
                  {message.recommendations.map((recommendation, recommendationIndex) => (
                    <div className="rounded-lg border border-border/70 bg-card/85 p-2 text-xs" key={`${recommendation.type}-${recommendationIndex}`}>
                      <p className="font-semibold text-foreground">{recommendation.title}</p>
                      <p className="mt-1 text-muted-foreground">{recommendation.rationale}</p>
                      {recommendation.fairness_impact ? (
                        <p className="mt-1 text-muted-foreground">
                          <span className="font-semibold text-foreground">Fairness impact:</span> {recommendation.fairness_impact}
                        </p>
                      ) : null}
                      {recommendation.coverage_impact ? (
                        <p className="mt-1 text-muted-foreground">
                          <span className="font-semibold text-foreground">Coverage impact:</span> {recommendation.coverage_impact}
                        </p>
                      ) : null}
                      {recommendation.constraint_rationale ? (
                        <p className="mt-1 text-muted-foreground">
                          <span className="font-semibold text-foreground">Constraint rationale:</span>{' '}
                          {recommendation.constraint_rationale}
                        </p>
                      ) : null}
                    </div>
                  ))}
                </div>
              ) : null}
              {message.role === 'assistant' && message.actionPayload ? (
                (() => {
                  const actionKey = `${message.actionPayload.action_type}-${JSON.stringify(message.actionPayload.params)}`
                  if (dismissedActions[actionKey]) return null
                  const isBusy = isExecutingAction === actionKey
                  return (
                    <div className="rounded-lg border border-primary/30 bg-primary/10 p-2 text-xs">
                      <p className="font-semibold text-foreground">{message.actionPayload.label}</p>
                      <p className="mt-1 text-muted-foreground">Owner confirmation required before execution.</p>
                      <div className="mt-2 flex gap-2">
                        <Button disabled={isBusy} onClick={() => confirmAction(message.actionPayload as AIActionPayload)} size="sm" variant="success">
                          {isBusy ? 'Running...' : 'Confirm'}
                        </Button>
                        <Button
                          disabled={isBusy}
                          onClick={() => {
                            void rejectAction(message.actionPayload as AIActionPayload)
                          }}
                          size="sm"
                          variant="outline"
                        >
                          Reject
                        </Button>
                      </div>
                    </div>
                  )
                })()
              ) : null}
            </div>
          ))}
        </div>
        <div className="flex gap-2">
          <textarea
            className="min-h-[4.5rem] w-full resize-y rounded-md border border-input bg-background px-3 py-2 text-sm ring-offset-background placeholder:text-muted-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 disabled:cursor-not-allowed disabled:opacity-50"
            maxLength={2000}
            onChange={(event) => setInput(event.target.value)}
            onKeyDown={(event) => {
              if (event.key === 'Enter' && !event.shiftKey) {
                event.preventDefault()
                sendMessage()
              }
            }}
            placeholder="Ask about fairness, coverage, or what to improve..."
            rows={3}
            value={input}
          />
          <Button disabled={isSending} onClick={sendMessage} type="button">
            {isSending ? 'Thinking...' : 'Send'}
          </Button>
        </div>
      </CardContent>
    </Card>
  )
}
