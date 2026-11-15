import { Check, Loader2, X } from 'lucide-react'
import { Message } from '@/components/chat/Message'
import { Button } from '@/components/ui/button'
import { Skeleton } from '@/components/ui/skeleton'
import { useAutomationRuns } from '@/lib/queries'

const SOURCES = { schedule: 'Schedule', event: 'Event', watch: 'Watch', test: 'Test' }

export function Time({ iso }) {
  return <time dateTime={iso}>{new Date(iso).toLocaleString(undefined, { dateStyle: 'medium', timeStyle: 'short' })}</time>
}

/** A run's result in words and an icon, so it never relies on colour alone. */
export function RunStatus({ status }) {
  if (status === 'running')
    return (
      <span className="inline-flex items-center gap-1 text-muted-foreground">
        <Loader2 className="size-3.5 animate-spin" aria-hidden="true" /> Running
      </span>
    )
  if (status === 'succeeded')
    return (
      <span className="inline-flex items-center gap-1 text-green-700">
        <Check className="size-3.5" aria-hidden="true" /> Succeeded
      </span>
    )
  return (
    <span className="inline-flex items-center gap-1 text-destructive">
      <X className="size-3.5" aria-hidden="true" /> Failed
    </span>
  )
}

function Run({ run }) {
  const tools = run.tool_calls ?? []
  const overridden = tools.filter((tool) => tool.overridden?.length)
  return (
    <li className="flex flex-col gap-2 border-t px-4 py-3 first:border-t-0">
      <p className="flex flex-wrap items-center gap-x-2 gap-y-1 text-xs">
        <span className="font-medium">
          <Time iso={run.started_at} />
        </span>
        <span className="text-muted-foreground">· {SOURCES[run.source] ?? run.source} ·</span>
        <RunStatus status={run.status} />
      </p>
      {(run.output || tools.length > 0) && <Message role="assistant" content={run.output} tools={tools} />}
      {overridden.map((tool, index) => (
        <p key={index} className="text-xs text-muted-foreground">
          {tool.label}: kept the approved value for {tool.overridden.join(', ')}
        </p>
      ))}
      {run.error && <p className="text-sm break-words text-destructive">{run.error}</p>}
    </li>
  )
}

/** The last 20 runs of one automation, newest first. */
export function RunHistory({ automationId }) {
  const runs = useAutomationRuns(automationId)
  if (runs.isPending)
    return (
      <div className="flex flex-col gap-2 p-4" role="status" aria-label="Loading run history">
        <Skeleton className="h-5 w-1/3" />
        <Skeleton className="h-12" />
      </div>
    )
  if (runs.isError)
    return (
      <div className="flex flex-wrap items-center gap-3 p-4">
        <p className="text-sm text-destructive">{runs.error.message}</p>
        <Button variant="outline" size="sm" onClick={() => runs.refetch()}>
          Retry
        </Button>
      </div>
    )
  if (runs.data.length === 0) return <p className="p-4 text-sm text-muted-foreground">No runs yet.</p>
  return (
    <ul className="flex flex-col" aria-label="Run history">
      {runs.data.map((run) => (
        <Run key={run.id} run={run} />
      ))}
    </ul>
  )
}
