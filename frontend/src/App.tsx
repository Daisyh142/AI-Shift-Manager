import { Redirect, Route, Switch } from 'wouter'
import { useAuth } from '@/hooks/useAuth'
import { Layout } from '@/components/Layout'
import { HomePage } from '@/pages/HomePage'
import { OwnerDashboard } from '@/pages/OwnerDashboard'
import { EmployeeDashboard } from '@/pages/EmployeeDashboard'
import { AllSchedules } from '@/pages/AllSchedules'
import { TimeOffRequests } from '@/pages/TimeOffRequests'
import { NotFound } from '@/pages/NotFound'
import { AIChat } from '@/components/AIChat'
import { AnalyticsPage } from '@/pages/AnalyticsPage'

function App() {
  const { isAuthenticated, isLoading, logout, user } = useAuth()

  if (isLoading) {
    return (
      <div className="grid min-h-screen place-items-center text-sm text-muted-foreground">
        <div className="surface-card px-6 py-4">Loading session...</div>
      </div>
    )
  }

  if (!isAuthenticated || !user) {
    return (
      <Switch>
        <Route path="/">
          <HomePage />
        </Route>
        <Route>
          <Redirect to="/" />
        </Route>
      </Switch>
    )
  }

  const ownerOnly = user.role === 'owner'

  return (
    <Layout onLogout={logout} user={user}>
      <Switch>
        <Route path="/">
          <Redirect to="/dashboard" />
        </Route>
        <Route path="/dashboard">
          {ownerOnly ? <OwnerDashboard /> : <EmployeeDashboard />}
        </Route>
        <Route path="/schedule">
          {ownerOnly ? <OwnerDashboard /> : <Redirect to="/dashboard" />}
        </Route>
        <Route path="/employees">
          {ownerOnly ? <OwnerDashboard /> : <Redirect to="/dashboard" />}
        </Route>
        <Route path="/requests">
          {ownerOnly ? <TimeOffRequests /> : <Redirect to="/dashboard" />}
        </Route>
        <Route path="/analytics">
          {ownerOnly ? <AnalyticsPage /> : <Redirect to="/dashboard" />}
        </Route>
        <Route path="/team-schedule">
          {!ownerOnly ? <AllSchedules /> : <Redirect to="/dashboard" />}
        </Route>
        <Route path="/my-requests">
          {!ownerOnly ? <TimeOffRequests /> : <Redirect to="/dashboard" />}
        </Route>
        <Route path="/ai">
          <AIChat />
        </Route>
        <Route>
          <NotFound />
        </Route>
      </Switch>
    </Layout>
  )
}

export default App
