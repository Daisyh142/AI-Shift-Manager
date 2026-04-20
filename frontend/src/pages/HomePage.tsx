import { LoginForm } from '@/components/LoginForm'
import { Sparkles, Calendar, Users, Clock, Shield, Zap } from 'lucide-react'

const features = [
  {
    icon: Sparkles,
    title: 'AI-Powered Scheduling',
    description: 'Let our AI create fair, optimized schedules in seconds',
  },
  {
    icon: Users,
    title: 'Fair Distribution',
    description: 'Balanced hours and shifts for every team member',
  },
  {
    icon: Clock,
    title: 'Time-Off Management',
    description: 'Seamless PTO requests and coverage handling',
  },
  {
    icon: Shield,
    title: 'Transparency',
    description: 'Clear fairness scores visible to everyone',
  },
]

export function HomePage() {
  return (
    <div className="min-h-screen bg-background">
      <header className="fixed top-0 left-0 right-0 z-50 bg-background/80 backdrop-blur-lg border-b border-border/50">
        <div className="container mx-auto px-4 h-16 flex items-center justify-between">
          <div className="flex items-center gap-3">
            <div className="w-10 h-10 rounded-xl gradient-primary flex items-center justify-center shadow-glow">
              <Sparkles className="w-5 h-5 text-primary-foreground" />
            </div>
            <span className="text-xl font-bold text-gradient">ShiftAI</span>
          </div>
          <nav className="hidden md:flex items-center gap-8">
            <a href="#features" className="text-sm text-muted-foreground hover:text-foreground transition-colors">
              Features
            </a>
            <a href="#login" className="text-sm text-muted-foreground hover:text-foreground transition-colors">
              Login
            </a>
          </nav>
        </div>
      </header>

      <section className="pt-32 pb-20 px-4">
        <div className="container mx-auto">
          <div className="grid lg:grid-cols-2 gap-12 items-center">
            <div className="text-center lg:text-left animate-slide-up">
              <div className="inline-flex items-center gap-2 px-4 py-2 rounded-full bg-primary/10 text-primary text-sm font-medium mb-6">
                <Zap className="w-4 h-4" />
                AI Powered Shift Management
              </div>
              <h1 className="text-4xl md:text-5xl lg:text-6xl font-bold text-foreground leading-tight">
                Smarter Schedules,
                <br />
                <span className="text-gradient">Happier Teams</span>
              </h1>
              <p className="mt-6 text-lg text-muted-foreground max-w-xl mx-auto lg:mx-0">
                This web app uses AI to make managing a team easier for you and your team. Let AI handle the complexity
                of shift scheduling—fair distribution, easy time-off requests, and full transparency for everyone.
              </p>

              <div className="grid grid-cols-2 gap-4 mt-10">
                {features.map((feature) => (
                  <div
                    key={feature.title}
                    className="p-4 rounded-xl bg-card border border-border/50 hover:border-primary/30 transition-colors group"
                  >
                    <feature.icon className="w-6 h-6 text-primary mb-2 group-hover:scale-110 transition-transform" />
                    <h3 className="font-semibold text-foreground text-sm">{feature.title}</h3>
                    <p className="text-xs text-muted-foreground mt-1">{feature.description}</p>
                  </div>
                ))}
              </div>
            </div>

            <div id="login" className="flex justify-center lg:justify-end animate-fade-in">
              <LoginForm />
            </div>
          </div>
        </div>
      </section>

      <section id="features" className="py-20 px-4">
        <div className="container mx-auto">
          <div className="text-center mb-12">
            <h2 className="text-3xl md:text-4xl font-bold text-foreground">Why Teams Love ShiftAI</h2>
            <p className="mt-3 text-muted-foreground max-w-2xl mx-auto">
              AI-powered tools that make managing a team easier for you and your team—smarter schedules and less guesswork.
            </p>
          </div>
          <div className="grid md:grid-cols-3 gap-8 max-w-4xl mx-auto">
            <div className="text-center p-6">
              <div className="w-16 h-16 rounded-2xl gradient-primary flex items-center justify-center mx-auto mb-4 shadow-glow">
                <Calendar className="w-8 h-8 text-primary-foreground" />
              </div>
              <h3 className="text-xl font-semibold text-foreground">For Employees</h3>
              <p className="mt-2 text-muted-foreground">View schedules, request time off, and swap shifts with ease.</p>
            </div>
            <div className="text-center p-6">
              <div className="w-16 h-16 rounded-2xl gradient-accent flex items-center justify-center mx-auto mb-4">
                <Users className="w-8 h-8 text-accent-foreground" />
              </div>
              <h3 className="text-xl font-semibold text-foreground">For Managers</h3>
              <p className="mt-2 text-muted-foreground">
                Chat with AI to create schedules, approve requests, and track fairness.
              </p>
            </div>
            <div className="text-center p-6">
              <div className="w-16 h-16 rounded-2xl bg-success/20 flex items-center justify-center mx-auto mb-4">
                <Shield className="w-8 h-8 text-success" />
              </div>
              <h3 className="text-xl font-semibold text-foreground">Fair & Transparent</h3>
              <p className="mt-2 text-muted-foreground">Everyone can see fairness scores. No more favoritism.</p>
            </div>
          </div>
        </div>
      </section>

      <footer className="py-8 px-4 border-t border-border/50">
        <div className="container mx-auto flex flex-col md:flex-row items-center justify-between gap-4">
          <div className="flex items-center gap-2">
            <div className="w-8 h-8 rounded-lg gradient-primary flex items-center justify-center">
              <Sparkles className="w-4 h-4 text-primary-foreground" />
            </div>
            <span className="font-semibold text-foreground">ShiftAI</span>
          </div>
          <p className="text-sm text-muted-foreground">© ShiftAI. Making scheduling fair for everyone.</p>
        </div>
      </footer>
    </div>
  )
}
