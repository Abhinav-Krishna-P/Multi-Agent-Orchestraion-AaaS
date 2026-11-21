import { Check, ChevronDown, X } from 'lucide-react'
import { useState } from 'react'
import { Button } from '@/components/ui/button'
import { Skeleton } from '@/components/ui/skeleton'
import { Badge } from '@/components/ui/badge'
import { useApiCallDays, useApiCallsPage, useApiRecentCalls } from '@/lib/queries'

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

function Failed({ onRetry, children }) {
  return (
    <div className="flex flex-col items-start gap-3 rounded-xl border p-6">
      <p className="text-sm text-destructive">{children}</p>
      <Button variant="outline" onClick={onRetry}>
        Retry
      </Button>
    </div>
  )
}

function CallList({ calls }) {
  return (
    <ul className="flex flex-col divide-y rounded-xl border">
      {calls.map((call) => (
        <Row key={call.id} call={call} />
      ))}
    </ul>
  )
}

// At most 7 buttons: first, last, the current page and its neighbours, with gaps as ellipses.
function pageItems(page, pages) {
  const shown = new Set([1, pages, page - 1, page, page + 1])
  if (page <= 3) [2, 3, 4, 5].forEach((n) => shown.add(n))
  if (page >= pages - 2) [pages - 1, pages - 2, pages - 3, pages - 4].forEach((n) => shown.add(n))
  const sorted = [...shown].filter((n) => n >= 1 && n <= pages).sort((a, b) => a - b).slice(0, 7)
  return sorted.flatMap((n, i) => (i > 0 && n - sorted[i - 1] > 1 ? [`gap${n}`, n] : [n]))
}

function Pagination({ page, pages, onPage }) {
  return (
    <nav aria-label="Pages" className="flex flex-wrap items-center justify-center gap-1 p-2">
      <Button variant="ghost" size="sm" disabled={page <= 1} onClick={() => onPage(page - 1)}>
        ‹ Prev
      </Button>
      {pageItems(page, pages).map((item) =>
        typeof item === 'string' ? (
          <span key={item} className="px-1 text-muted-foreground" aria-hidden="true">
            …
          </span>
        ) : (
          <Button
            key={item}
            size="sm"
            variant={item === page ? 'secondary' : 'ghost'}
            aria-current={item === page ? 'page' : undefined}
            aria-label={`Page ${item}`}
            onClick={() => onPage(item)}
          >
            {item}
          </Button>
        ),
      )}
      <Button variant="ghost" size="sm" disabled={page >= pages} onClick={() => onPage(page + 1)}>
        Next ›
      </Button>
    </nav>
  )
}

function DayCalls({ agentId, day }) {
  const [page, setPage] = useState(1)
  const result = useApiCallsPage(agentId, day, page)
  if (result.isPending) return <Skeleton className="m-3 h-16" role="status" aria-label="Loading calls" />
  if (result.isError) return <div className="p-3"><Failed onRetry={() => result.refetch()}>This day couldn&apos;t load.</Failed></div>
  const { calls, pages } = result.data
  return (
    <div className="border-t">
      <CallList calls={calls} />
      {pages > 1 && <Pagination page={page} pages={pages} onPage={setPage} />}
    </div>
  )
}

const dayLabel = ({ date }) => {
  const local = (d) => d.toLocaleDateString('en-CA')
  const now = new Date()
  if (date === local(now)) return 'Today'
  if (date === local(new Date(now.getFullYear(), now.getMonth(), now.getDate() - 1))) return 'Yesterday'
  return new Date(`${date}T12:00:00`).toLocaleDateString('en-US', { weekday: 'short', month: 'short', day: 'numeric' })
}

function Day({ agentId, day }) {
  const [open, setOpen] = useState(false)
  return (
    <li>
      <button
        type="button"
        aria-expanded={open}
        onClick={() => setOpen(!open)}
        className="flex w-full cursor-pointer items-center gap-2 p-3 text-left text-sm outline-none hover:bg-muted/50 focus-visible:ring-3 focus-visible:ring-ring/50 focus-visible:ring-inset"
      >
        <ChevronDown className={`size-4 transition-transform ${open ? '' : '-rotate-90'}`} aria-hidden="true" />
        <span className="font-medium">{dayLabel(day)}</span>
        <span className="ml-auto flex items-center gap-2">
          <Badge variant="secondary">{day.calls} {day.calls === 1 ? 'call' : 'calls'}</Badge>
          {day.failed > 0 && <Badge variant="destructive">{day.failed} failed</Badge>}
        </span>
      </button>
      {open && <DayCalls agentId={agentId} day={day.date} />}
    </li>
  )
}

export function CallLog({ agentId }) {
  const recent = useApiRecentCalls(agentId)
  const days = useApiCallDays(agentId)

  let body
  if (recent.isPending || days.isPending) {
    body = <Skeleton className="h-24" role="status" aria-label="Loading calls" />
  } else if (recent.isError || days.isError) {
    body = (
      <Failed
        onRetry={() => {
          recent.refetch()
          days.refetch()
        }}
      >
        The calls couldn&apos;t load.
      </Failed>
    )
  } else if (recent.data.calls.length === 0) {
    body = <p className="rounded-xl border border-dashed p-6 text-center text-sm text-muted-foreground">No calls yet.</p>
  } else {
    body = (
      <>
        <CallList calls={recent.data.calls} />
        <h3 className="mt-2 text-sm font-medium text-muted-foreground">By day</h3>
        <ul className="flex flex-col divide-y rounded-xl border">
          {days.data.days.map((day) => (
            <Day key={day.date} agentId={agentId} day={day} />
          ))}
        </ul>
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
