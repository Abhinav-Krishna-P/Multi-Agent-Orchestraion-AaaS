import { ArrowLeft, Check } from 'lucide-react'
import { Link, useNavigate, useParams, useSearchParams } from 'react-router-dom'
import { Button } from '@/components/ui/button'
import { Skeleton } from '@/components/ui/skeleton'
import { useAgent } from '@/lib/queries'
import { cn } from '@/lib/utils'
import Basics from './Basics'
import Behavior from './Behavior'
import Deploy from './Deploy'
import Knowledge from './Knowledge'
import Model from './Model'
import Tools from './Tools'

// The steps are a real sequence, so they are numbered. A later stage adds Apps.
const STEPS = [
  { key: 'basics', label: 'Basics', Component: Basics },
  { key: 'behavior', label: 'Behavior', Component: Behavior },
  { key: 'model', label: 'Model', Component: Model },
  { key: 'knowledge', label: 'Knowledge', Component: Knowledge },
  { key: 'tools', label: 'Tools', Component: Tools },
  { key: 'deploy', label: 'Deploy', Component: Deploy },
]

function Stepper({ current, canJump, onJump }) {
  const currentIndex = STEPS.findIndex((step) => step.key === current)
  return (
    <ol className="flex flex-wrap items-center gap-x-2 gap-y-2" aria-label="Steps">
      {STEPS.map((step, index) => {
        const active = index === currentIndex
        const done = index < currentIndex
        return (
          <li key={step.key} className="flex items-center gap-2">
            <button
              type="button"
              disabled={!canJump}
              aria-current={active ? 'step' : undefined}
              onClick={() => onJump(step.key)}
              className={cn(
                'flex items-center gap-2 rounded-lg px-2 py-1.5 text-sm font-medium outline-none transition-colors focus-visible:ring-3 focus-visible:ring-ring/50',
                active ? 'text-foreground' : 'text-muted-foreground',
                canJump && !active && 'cursor-pointer hover:bg-muted hover:text-foreground',
              )}
            >
              <span
                className={cn(
                  'flex size-6 items-center justify-center rounded-full border text-xs',
                  active && 'border-primary bg-primary text-primary-foreground',
                  done && 'border-primary/30 bg-primary/10 text-primary',
                )}
              >
                {done ? <Check className="size-3.5" aria-hidden="true" /> : index + 1}
              </span>
              {step.label}
            </button>
            {index < STEPS.length - 1 && <span className="h-px w-6 bg-border" aria-hidden="true" />}
          </li>
        )
      })}
    </ol>
  )
}

export default function AgentWizard() {
  const { agentId } = useParams()
  const [searchParams, setSearchParams] = useSearchParams()
  const navigate = useNavigate()
  const agent = useAgent(agentId)

  const isNew = !agentId
  const requested = searchParams.get('step')
  const stepKey = isNew ? 'basics' : STEPS.some((step) => step.key === requested) ? requested : 'basics'
  const index = STEPS.findIndex((step) => step.key === stepKey)
  const { Component } = STEPS[index]

  const goTo = (key) => setSearchParams({ step: key })
  const next = () => goTo(STEPS[index + 1].key)
  const back = () => goTo(STEPS[index - 1].key)
  // A new agent is saved as a draft by the first step, so leaving the wizard never loses work.
  const onCreated = (created) => navigate(`/app/agents/${created.id}?step=behavior`, { replace: true })

  return (
    <div className="flex flex-col gap-6 p-6">
      <div>
        <Button variant="ghost" size="sm" asChild className="-ml-2 text-muted-foreground">
          <Link to="/app/agents">
            <ArrowLeft aria-hidden="true" /> Your agents
          </Link>
        </Button>
        <h1 className="mt-2 text-2xl font-semibold">
          {isNew ? 'Create agent' : agent.data ? `Edit ${agent.data.name}` : 'Edit agent'}
        </h1>
      </div>

      <Stepper current={stepKey} canJump={!isNew && Boolean(agent.data)} onJump={goTo} />

      {!isNew && agent.isPending ? (
        <div className="flex flex-col gap-4" role="status" aria-label="Loading agent">
          <Skeleton className="h-10" />
          <Skeleton className="h-28" />
        </div>
      ) : !isNew && agent.isError ? (
        <div className="flex flex-col items-start gap-3 rounded-xl border p-6">
          <p className="text-sm text-destructive">
            {agent.error?.status === 404 ? "This agent doesn't exist any more." : "This agent couldn't load."}
          </p>
          {agent.error?.status === 404 ? (
            <Button variant="outline" asChild>
              <Link to="/app/agents">Back to your agents</Link>
            </Button>
          ) : (
            <Button variant="outline" onClick={() => agent.refetch()}>
              Retry
            </Button>
          )}
        </div>
      ) : (
        // Keyed by agent and step so each step starts from the saved values.
        <Component
          key={`${agentId ?? 'new'}-${stepKey}`}
          agent={agent.data ?? null}
          onCreated={onCreated}
          onNext={next}
          onBack={back}
          goTo={goTo}
        />
      )}
    </div>
  )
}
