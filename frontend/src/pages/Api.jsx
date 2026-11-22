import { KeyRound } from 'lucide-react'
import { useEffect } from 'react'
import { Link, useNavigate, useParams } from 'react-router-dom'
import { AgentSelect } from '@/components/AgentSelect'
import { ApiSettings } from '@/components/api/ApiSettings'
import { CallLog } from '@/components/api/CallLog'
import { CodeSamples } from '@/components/api/CodeSamples'
import { KeyList } from '@/components/api/KeyList'
import { Button } from '@/components/ui/button'
import { Skeleton } from '@/components/ui/skeleton'
import { useAgentApi, useAgents } from '@/lib/queries'

function Retry({ children, onRetry }) {
  return (
    <div className="flex flex-col items-start gap-3 rounded-xl border p-6">
      <p className="text-sm text-destructive">{children}</p>
      <Button variant="outline" onClick={onRetry}>
        Retry
      </Button>
    </div>
  )
}

function AgentApi({ agent }) {
  const info = useAgentApi(agent.id)
  if (info.isPending) {
    return (
      <div className="flex flex-col gap-4" role="status" aria-label="Loading API settings">
        <Skeleton className="h-24" />
        <Skeleton className="h-32" />
      </div>
    )
  }
  if (info.isError) return <Retry onRetry={() => info.refetch()}>The API settings couldn&apos;t load.</Retry>
  return (
    <div className="flex flex-col gap-6">
      {agent.status !== 'live' && (
        <p role="status" className="rounded-xl border bg-muted/50 p-3 text-sm text-muted-foreground">
          Calls are refused until this agent is live.
        </p>
      )}
      <KeyList agent={agent} keys={info.data.keys} />
      <ApiSettings agent={agent} settings={info.data.settings} actions={info.data.actions} />
      <CodeSamples />
      <CallLog agentId={agent.id} />
    </div>
  )
}

export default function Api() {
  const { agentId } = useParams()
  const navigate = useNavigate()
  const agents = useAgents()
  const pickable = agents.data ?? []
  const agent = pickable.find((a) => a.id === agentId)

  const firstId = (pickable.find((a) => a.status === 'live') ?? pickable[0])?.id
  useEffect(() => {
    if (!agentId && firstId) navigate(`/app/api/${firstId}`, { replace: true })
  }, [agentId, firstId, navigate])

  let body
  if (agents.isPending) {
    body = (
      <div className="flex flex-col gap-4" role="status" aria-label="Loading API">
        <Skeleton className="h-10" />
        <Skeleton className="h-32" />
      </div>
    )
  } else if (agents.isError) {
    body = <Retry onRetry={() => agents.refetch()}>Your agents couldn&apos;t load.</Retry>
  } else if (pickable.length === 0) {
    body = (
      <div className="flex flex-col items-center gap-3 rounded-xl border border-dashed p-10 text-center">
        <p className="text-sm text-muted-foreground">Deploy an agent to call it from your own program.</p>
        <Button asChild>
          <Link to="/app/agents/new">Create agent</Link>
        </Button>
      </div>
    )
  } else if (agentId && !agent) {
    body = <p className="rounded-xl border p-6 text-sm text-muted-foreground">This agent isn&apos;t available. Pick another one above.</p>
  } else if (agent) {
    body = <AgentApi key={agent.id} agent={agent} />
  }

  return (
    <div className="flex flex-col gap-4 p-4 md:p-6">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div className="min-w-0">
          <h1 className="flex items-center gap-2 text-2xl font-semibold">
            <KeyRound className="size-6 text-primary" aria-hidden="true" /> API
          </h1>
          <p className="mt-1 text-sm text-muted-foreground">Call your agent from your own program with a key.</p>
        </div>
        {pickable.length > 0 && (
          <AgentSelect
            agents={pickable}
            value={agent?.id}
            onChange={(id) => navigate(`/app/api/${id}`)}
            className="w-full sm:w-56"
          />
        )}
      </div>
      {body}
    </div>
  )
}
