import { Check, ChevronDown, X } from 'lucide-react'
import { useState } from 'react'
import { Button } from '@/components/ui/button'
import { Skeleton } from '@/components/ui/skeleton'
import { useApiCalls } from '@/lib/queries'

const seconds = (ms) => `${(ms / 1000).toFixed(1)} s`

function Detail({ title, children }) {
  return (
    <div>
      <p className="text-xs font-medium text-muted-foreground">{title}</p>
      {children}
    </div>
  )
}

function Row({ call }) {
  const [open, setOpen] = useState(false)
  const ok = call.outcome === 'ok'
  return (
    <li>
      <button
        type="button"
        aria-expanded={open}
        onClick={() => setOpen(!open)}
        className="flex w-full cursor-pointer flex-col gap-1 p-3 text-left outline-none hover:bg-muted/50 focus-visible:ring-3 focus-visible:ring-ring/50 focus-visible:ring-inset"
      >
        <span className="flex flex-wrap items-center gap-x-3 gap-y-1 text-xs text-muted-foreground">
          <time dateTime={call.created_at}>{new Date(call.created_at).toLocaleString(undefined, { dateStyle: 'medium', timeStyle: 'short' })}</time>
          <span className={ok ? 'inline-flex items-center gap-1' : 'inline-flex items-center gap-1 text-destructive'}>
            {ok ? <Check className="size-3.5" aria-hidden="true" /> : <X className="size-3.5" aria-hidden="true" />}
            {call.outcome}
          </span>
          <span>{seconds(call.duration_ms)}</span>
          <ChevronDown className={`ml-auto size-4 transition-transform ${open ? 'rotate-180' : ''}`} aria-hidden="true" />
        </span>
        <span className="truncate text-sm">{call.message}</span>
        <span className="truncate text-sm text-muted-foreground">{call.reply || 'No reply'}</span>
      </button>
      {open && (
        <div className="flex flex-col gap-3 border-t bg-muted/30 p-3 text-sm">
          <Detail title="Message">
            <p className="whitespace-pre-wrap">{call.message}</p>
          </Detail>
          <Detail title="Reply">
            <p className="whitespace-pre-wrap">{call.reply || 'No reply'}</p>
          </Detail>
          {call.tools_used.length > 0 && (
            <Detail title="Tools used">
              <ul className="list-disc pl-5">
                {call.tools_used.map((tool, i) => (
                  <li key={i}>
                    {tool.name}: {tool.ok ? 'ok' : 'failed'}
                    {tool.overridden?.length > 0 && ` (removed: ${tool.overridden.join(', ')})`}
                  </li>
                ))}
              </ul>
            </Detail>
          )}
          {call.sources.length > 0 && (
            <Detail title="Sources">
              <ul className="list-disc pl-5">
                {call.sources.map((source, i) => (
                  <li key={i}>
                    {source.document_name}
                    {source.page != null && `, page ${source.page}`}
                  </li>
                ))}
              </ul>
            </Detail>
          )}
          <p className="text-xs text-muted-foreground">Key: {call.key_name ?? 'revoked key'}</p>
        </div>
      )}
    </li>
  )
}

export function CallLog({ agentId }) {
  const calls = useApiCalls(agentId)
  const rows = calls.data?.pages.flatMap((page) => page.calls) ?? []

  let body
  if (calls.isPending) {
    body = <Skeleton className="h-24" role="status" aria-label="Loading calls" />
  } else if (calls.isError) {
    body = (
      <div className="flex flex-col items-start gap-3 rounded-xl border p-6">
        <p className="text-sm text-destructive">The calls couldn&apos;t load.</p>
        <Button variant="outline" onClick={() => calls.refetch()}>
          Retry
        </Button>
      </div>
    )
  } else if (rows.length === 0) {
    body = <p className="rounded-xl border border-dashed p-6 text-center text-sm text-muted-foreground">No calls yet.</p>
  } else {
    body = (
      <>
        <ul className="flex flex-col divide-y rounded-xl border">
          {rows.map((call) => (
            <Row key={call.id} call={call} />
          ))}
        </ul>
        {calls.hasNextPage && (
          <Button variant="outline" className="self-start" disabled={calls.isFetchingNextPage} onClick={() => calls.fetchNextPage()}>
            {calls.isFetchingNextPage ? 'Loading…' : 'Load more'}
          </Button>
        )}
      </>
    )
  }

  return (
    <section className="flex flex-col gap-3" aria-labelledby="api-calls-heading">
      <h2 id="api-calls-heading" className="text-lg font-semibold">
        Recent calls
      </h2>
      {body}
    </section>
  )
}
