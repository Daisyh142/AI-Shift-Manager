import { useState, type FormEvent } from 'react'
import { useAuth } from '@/hooks/useAuth'
import { ApiError } from '@/lib/api'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { useToast } from '@/hooks/useToast'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { ArrowRight, Sparkles } from 'lucide-react'

export function LoginForm() {
  const { login, tryDemo } = useAuth()
  const { toast } = useToast()
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [isSubmitting, setIsSubmitting] = useState(false)
  const [error, setError] = useState<string | null>(null)

  async function onSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    setIsSubmitting(true)
    setError(null)
    try {
      await login(email, password)
      toast({ title: 'Signed in', description: 'Welcome back to WorkForYou.' })
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Login failed. Please try again.')
    } finally {
      setIsSubmitting(false)
    }
  }

  async function onTryDemo() {
    setIsSubmitting(true)
    setError(null)
    try {
      await tryDemo()
      toast({ title: 'Demo ready', description: 'Seed data loaded and owner account signed in.' })
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Demo sign in failed.')
    } finally {
      setIsSubmitting(false)
    }
  }

  return (
    <Card className="w-full max-w-md border-primary/20 shadow-[0_20px_40px_rgba(15,118,110,0.15)]">
      <CardHeader className="space-y-3">
        <div className="inline-flex h-12 w-12 items-center justify-center rounded-xl gradient-primary shadow-glow">
          <Sparkles className="h-6 w-6 text-primary-foreground" />
        </div>
        <CardTitle className="text-2xl">Welcome back</CardTitle>
        <CardDescription>Sign in with your account or try the demo data.</CardDescription>
      </CardHeader>
      <CardContent>
        <form className="space-y-5" onSubmit={onSubmit}>
          <div className="space-y-2">
            <label className="text-sm font-semibold" htmlFor="email">
              Email
            </label>
            <Input
              autoComplete="email"
              id="email"
              onChange={(event) => setEmail(event.target.value)}
              placeholder="owner@demo.com or employee@demo.com"
              required
              type="email"
              value={email}
            />
          </div>
          <div className="space-y-2">
            <label className="text-sm font-semibold" htmlFor="password">
              Password
            </label>
            <Input
              autoComplete="current-password"
              id="password"
              onChange={(event) => setPassword(event.target.value)}
              placeholder="demo"
              required
              type="password"
              value={password}
            />
          </div>
          {error ? <p className="text-sm text-destructive">{error}</p> : null}
          <Button className="w-full" disabled={isSubmitting} type="submit" variant="gradient">
            {isSubmitting ? 'Signing in...' : 'Sign in'}
            <ArrowRight className="h-4 w-4" />
          </Button>
          <Button className="w-full" disabled={isSubmitting} onClick={onTryDemo} type="button" variant="outline">
            <Sparkles className="h-4 w-4" />
            Try Demo Data
          </Button>
          <p className="text-center text-xs text-muted-foreground">
            Demo is auto seeded when you click the demo button.
          </p>
        </form>
      </CardContent>
    </Card>
  )
}
