import { useState } from 'react'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
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
}

export function AIChat({ scheduleRunId, onActionExecuted }: AIChatProps) {
  const { toast } = useToast()
  const [input, setInput] = useState('')
  const [isSending, setIsSending] = useState(false)
  const [isExecutingAction, setIsExecutingAction] = useState<string | null>(null)
  const [dismissedActions, setDismissedActions] = useState<Record<string, true>>({})
  const [messages, setMessages] = useState<Message[]>([
    {
      role: 'assistant',
      content:
        'AI assistant is connected. Ask about fairness, coverage, or what to improve before regenerating a schedule.',
    },
  ])

  // Sends the current input to the AI chat endpoint and appends the response.
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
      const response = await apiClient.chatAI({
        message: trimmed,
        context: scheduleRunId ? { schedule_run_id: scheduleRunId } : undefined,
        mode: 'recommendation_only',
      })
      setMessages((prev) => [
        ...prev,
        {
          role: 'assistant',
          content: response.assistant_message,
          recommendations: response.recommendations,
          actionPayload: response.action_payload ?? null,
        },
      ])
    } catch (err) {
      const message = err instanceof ApiError ? err.message : 'AI is unavailable right now. Please try again.'
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

  // Executes a confirmed AI action through the deterministic backend endpoint.
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
      toast({
        title: 'Action failed',
        description: err instanceof Error ? err.message : 'Unable to execute confirmed action.',
        variant: 'error',
      })
    } finally {
      setIsExecutingAction(null)
    }
  }

  // Dismisses an AI action and logs the rejection for observability.
  async function rejectAction(actionPayload: AIActionPayload) {
    const actionKey = `${actionPayload.action_type}-${JSON.stringify(actionPayload.params)}`
    setDismissedActions((prev) => ({ ...prev, [actionKey]: true }))
    try {
      await apiClient.logAIFeedback({
        action_type: actionPayload.action_type,
        decision: 'rejected',
        schedule_run_id: scheduleRunId ?? undefined,
      })
    } catch {
      // Non-blocking — a failed feedback log should never interrupt the owner's flow.
    }
    toast({ title: 'Action skipped', description: 'No changes were applied.' })
  }

  return (
    <Card className="border-primary/15">
      <CardHeader>
        <CardTitle className="flex items-center gap-2 text-base">
          <Sparkles className="h-4 w-4 text-primary" />
          Shift Manager AI Assistant (Placeholder)
        </CardTitle>
      </CardHeader>
      <CardContent className="space-y-3">
        <div className="max-h-64 space-y-2 overflow-auto rounded-xl border bg-muted/30 p-3">
          {messages.map((message, index) => (
            <div className="space-y-2" key={`${message.role}-${index}`}>
              <p className="text-sm leading-relaxed">
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
          <Input
            onChange={(event) => setInput(event.target.value)}
            onKeyDown={(event) => {
              if (event.key === 'Enter') sendMessage()
            }}
            placeholder="Ask about schedule fairness..."
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
