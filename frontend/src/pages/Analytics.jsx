import { BarChart3, ChevronLeft, ChevronRight } from 'lucide-react'
import { useEffect, useState } from 'react'
import { Link, useNavigate, useParams, useSearchParams } from 'react-router-dom'
import { AgentSelect } from '@/components/AgentSelect'
import { ApiReport } from '@/components/analytics/ApiAnalytics'
import { AutomationReport } from '@/components/analytics/AutomationAnalytics'
import { ActivitySection, Tile, ms, number } from '@/components/analytics/parts'
import { Button } from '@/components/ui/button'
import { Skeleton } from '@/components/ui/skeleton'
import { Tabs } from '@/components/ui/tabs'
import { useAgents, useAnalytics, useApiAnalytics, useAutomationAnalytics } from '@/lib/queries'
import { cn } from '@/lib/utils'

const RANGES = [
  { value: '7d', label: '7 days' },
  { value: '30d', label: '30 days' },
  { value: '90d', label: '90 days' },
]
const SERIES = [
  { key: 'messages', label: 'Messages' },
  { key: 'tool_calls', label: 'Tool calls' },
]
const TABS = [
  { value: 'chat', label: 'Chat' },
  { value: 'automations', label: 'Automations' },
  { value: 'api', label: 'API' },
]
const PAGE_SIZE = 10
const TYPE_NAMES = { builtin: 'Built-in', api: 'Outside service', knowledge_base: 'Knowledge base', composio: 'Connected app' }

function Report({ data }) {
  const { totals, days, tools } = data
  const quiet = totals.messages === 0 && totals.tool_calls === 0 && totals.sessions === 0
  return (
    <div className="flex flex-col gap-5">
      <div className="grid grid-cols-2 gap-3 md:grid-cols-3 xl:grid-cols-5">
        <Tile label="Chats" value={number(totals.sessions)} />
        <Tile label="Messages" value={number(totals.messages)} />
        <Tile label="Tool calls" value={number(totals.tool_calls)} note={totals.tool_failures ? `${number(totals.tool_failures)} failed` : null} />
        <Tile label="Tool success" value={totals.success_rate == null ? '–' : `${Math.round(totals.success_rate * 100)}%`} />
        <Tile label="Average tool time" value={ms(totals.avg_tool_ms)} />
        <Tile label="Knowledge-base searches" value={number(totals.kb_searches)} />
        <Tile label="Actions approved" value={number(totals.approved)} note={`${number(totals.rejected)} rejected`} />
        <Tile label="Connection problems" value={number(totals.connection_problems)} />
        <Tile label="Documents added" value={number(totals.documents)} />
      </div>

      <ActivitySection
        id="activity-heading"
        title="Activity per day"
        days={days}
        series={SERIES}
        label="Messages and tool calls per day"
        quiet={quiet}
        quietText="No activity in this period yet."
      />

      <ToolsTable tools={tools} />
      <p className="text-xs text-muted-foreground">New activity can take a minute to appear.</p>
    </div>
  )
}

/** The tools used, by the name the user knows (the backend merges an app's actions into one row), 10 per page. */
function ToolsTable({ tools }) {
  const [wanted, setPage] = useState(0)
  const pages = Math.ceil(tools.length / PAGE_SIZE)
  const page = Math.min(wanted, Math.max(pages - 1, 0)) // a refresh with fewer rows stays on a real page
  const first = page * PAGE_SIZE
  const shown = tools.slice(first, first + PAGE_SIZE)
  return (
    <section className="rounded-md border bg-background" aria-labelledby="tools-heading">
      <h2 id="tools-heading" className="border-b px-4 py-3 text-sm font-semibold">Tools</h2>
      {tools.length === 0 ? (
        <p className="px-4 py-6 text-sm text-muted-foreground">No tools used in this period.</p>
      ) : (
        <div className="overflow-x-auto">
          <table className="w-full text-left text-sm">
            <thead className="text-xs text-muted-foreground">
              <tr>
                <th className="px-4 py-2 font-medium">Tool</th>
                <th className="px-4 py-2 font-medium">Type</th>
                <th className="px-4 py-2 text-right font-medium">Calls</th>
                <th className="px-4 py-2 text-right font-medium">Failed</th>
                <th className="hidden px-4 py-2 text-right font-medium sm:table-cell">Average time</th>
              </tr>
            </thead>
            <tbody>
              {shown.map((tool) => (
                <tr key={tool.name} className="border-t">
                  <td className="px-4 py-2 font-medium">{tool.name}</td>
                  <td className="px-4 py-2 text-muted-foreground">{TYPE_NAMES[tool.type] ?? tool.type}</td>
                  <td className="px-4 py-2 text-right tabular-nums">{number(tool.calls)}</td>
                  <td className={cn('px-4 py-2 text-right tabular-nums', tool.failures > 0 && 'text-destructive')}>{number(tool.failures)}</td>
                  <td className="hidden px-4 py-2 text-right tabular-nums sm:table-cell">{ms(tool.avg_ms)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      {pages > 1 && (
        <nav className="flex flex-wrap items-center justify-between gap-3 border-t px-4 py-2" aria-label="Tools pages">
          <p className="text-xs text-muted-foreground tabular-nums" aria-live="polite">
            {first + 1}–{first + shown.length} of {tools.length}
          </p>
          <div className="flex gap-2">
            <Button variant="outline" size="sm" disabled={page === 0} onClick={() => setPage(page - 1)}>
              <ChevronLeft aria-hidden="true" /> Previous
            </Button>
            <Button variant="outline" size="sm" disabled={page >= pages - 1} onClick={() => setPage(page + 1)}>
              Next <ChevronRight aria-hidden="true" />
            </Button>
          </div>
        </nav>
      )}
    </section>
  )
}

export default function Analytics() {
  const { agentId } = useParams()
  const navigate = useNavigate()
  const agents = useAgents()
  const [range, setRange] = useState('7d')
  const [params, setParams] = useSearchParams()
  const tab = ['automations', 'api'].includes(params.get('tab')) ? params.get('tab') : 'chat'
  const chat = useAnalytics(agentId, range, tab === 'chat')
  const automations = useAutomationAnalytics(agentId, range, tab === 'automations')
  const api = useApiAnalytics(agentId, range, tab === 'api')
  const analytics = { chat, automations, api }[tab]
  const selectTab = (value) => setParams(value === 'chat' ? {} : { tab: value }, { replace: true })
  const list = agents.data ?? []

  // With no agent in the address, show the first one.
  const firstId = list[0]?.id
  useEffect(() => {
    if (!agentId && firstId) navigate({ pathname: `/app/analytics/${firstId}`, search: params.toString() }, { replace: true })
  }, [agentId, firstId, navigate, params])

  let body
  if (agents.isPending || (agentId && analytics.isPending)) {
    body = (
      <div className="flex flex-col gap-3" role="status" aria-label="Loading analytics">
        <div className="grid grid-cols-2 gap-3 md:grid-cols-3 xl:grid-cols-5">
          {Array.from({ length: 5 }, (_, i) => (
            <Skeleton key={i} className="h-20" />
          ))}
        </div>
        <Skeleton className="h-64" />
      </div>
    )
  } else if (agents.isError) {
    body = (
      <div className="flex flex-col items-start gap-3 rounded-xl border p-6">
        <p className="text-sm text-destructive">Your agents couldn&apos;t load.</p>
        <Button variant="outline" onClick={() => agents.refetch()}>
          Retry
        </Button>
      </div>
    )
  } else if (list.length === 0) {
    body = (
      <div className="flex flex-col items-center gap-3 rounded-xl border border-dashed p-10 text-center">
        <p className="text-sm text-muted-foreground">Create an agent and chat with it to see its analytics here.</p>
        <Button asChild>
          <Link to="/app/agents/new">Create agent</Link>
        </Button>
      </div>
    )
  } else if (analytics.isError && analytics.error?.status === 404) {
    body = <p className="rounded-xl border p-6 text-sm text-muted-foreground">This agent doesn&apos;t exist any more. Pick another one above.</p>
  } else if (analytics.isError) {
    body = (
      <div className="flex flex-col items-start gap-3 rounded-xl border p-6">
        <p className="text-sm text-destructive">{analytics.error?.message ?? "Analytics couldn't load."}</p>
        <Button variant="outline" onClick={() => analytics.refetch()}>
          Retry
        </Button>
      </div>
    )
  } else if (analytics.data && !analytics.data.enabled) {
    body = (
      <p className="rounded-xl border border-dashed p-10 text-center text-sm text-muted-foreground">
        Analytics isn&apos;t set up on this server yet.
      </p>
    )
  } else if (analytics.data) {
    // Keyed: another agent or period starts the tools table on its first page.
    body = {
      chat: <Report key={`${agentId}:${range}`} data={analytics.data} />,
      automations: <AutomationReport data={analytics.data} />,
      api: <ApiReport data={analytics.data} />,
    }[tab]
  }

  return (
    <div className="flex flex-col gap-6 p-6">
      <div className="flex flex-wrap items-center justify-between gap-4">
        <h1 className="flex items-center gap-2 text-2xl font-semibold">
          <BarChart3 className="size-6 text-primary" aria-hidden="true" /> Analytics
        </h1>
        <div className="flex flex-wrap items-center gap-3">
          {list.length > 0 && (
            <AgentSelect agents={list} value={agentId} onChange={(id) => navigate({ pathname: `/app/analytics/${id}`, search: params.toString() })} className="w-56" />
          )}
          <div className="flex rounded-lg border p-0.5" role="group" aria-label="Period">
            {RANGES.map((option) => (
              <button
                key={option.value}
                type="button"
                aria-pressed={range === option.value}
                onClick={() => setRange(option.value)}
                className={cn(
                  'cursor-pointer rounded-md px-3 py-1.5 text-sm outline-none transition-colors focus-visible:ring-3 focus-visible:ring-ring/50',
                  range === option.value ? 'bg-primary/10 font-medium text-primary' : 'text-muted-foreground hover:text-foreground',
                )}
              >
                {option.label}
              </button>
            ))}
          </div>
        </div>
      </div>
      <Tabs id="analytics" label="Analytics" tabs={TABS} value={tab} onChange={selectTab}>
        {body}
      </Tabs>
    </div>
  )
}
