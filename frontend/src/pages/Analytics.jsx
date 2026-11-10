import { BarChart3 } from 'lucide-react'
import { useEffect, useRef, useState } from 'react'
import { Link, useNavigate, useParams } from 'react-router-dom'
import { AgentSelect } from '@/components/AgentSelect'
import { Button } from '@/components/ui/button'
import { Skeleton } from '@/components/ui/skeleton'
import { useAgents, useAnalytics } from '@/lib/queries'
import { cn } from '@/lib/utils'

const RANGES = [
  { value: '7d', label: '7 days' },
  { value: '30d', label: '30 days' },
  { value: '90d', label: '90 days' },
]
// Validated with the dataviz palette checks (colour-blind separation and 3:1 contrast) on
// white and on the dark surface. Each series keeps its colour; text never takes it.
const SERIES = [
  { key: 'messages', label: 'Messages', className: 'fill-[#2a78d6] dark:fill-[#3987e5]', swatch: 'bg-[#2a78d6] dark:bg-[#3987e5]' },
  { key: 'tool_calls', label: 'Tool calls', className: 'fill-[#eb6834] dark:fill-[#d95926]', swatch: 'bg-[#eb6834] dark:bg-[#d95926]' },
]
const TYPE_NAMES = { builtin: 'Built-in', api: 'Outside service', knowledge_base: 'Knowledge base', composio: 'Connected app' }

const number = (value) => (value == null ? '–' : new Intl.NumberFormat().format(value))
const day = (iso, options = { day: 'numeric', month: 'short' }) => new Date(`${iso}T00:00`).toLocaleDateString(undefined, options)
const ms = (value) => (value == null ? '–' : value >= 1000 ? `${(value / 1000).toFixed(1)} s` : `${value} ms`)

function Tile({ label, value, note }) {
  return (
    <div className="rounded-md border bg-background p-4">
      <p className="text-xs text-muted-foreground">{label}</p>
      <p className="mt-1 text-2xl font-semibold tabular-nums">{value}</p>
      {note && <p className="mt-0.5 text-xs text-muted-foreground">{note}</p>}
    </div>
  )
}

/** A bar with only its top corners rounded: the end that carries the value. */
function barPath(x, y, width, height, radius = 4) {
  const r = Math.min(radius, width / 2, height)
  return `M${x},${y + height}V${y + r}Q${x},${y} ${x + r},${y}H${x + width - r}Q${x + width},${y} ${x + width},${y + r}V${y + height}Z`
}

function ActivityChart({ days }) {
  const [hover, setHover] = useState(null) // { index, left } with left in pixels from the chart's edge
  const svgRef = useRef(null)
  const width = 720
  const height = 220
  const pad = { top: 12, right: 8, bottom: 26, left: 34 }
  const plotW = width - pad.left - pad.right
  const plotH = height - pad.top - pad.bottom
  const peak = Math.max(1, ...days.flatMap((d) => [d.messages, d.tool_calls]))
  const step = Math.pow(10, Math.floor(Math.log10(peak)))
  const top = Math.ceil(peak / step) * step
  const ticks = Number.isInteger(top / 2) ? [0, top / 2, top] : [0, top] // never "0.5 messages"
  const slot = plotW / days.length
  const gap = 2 // surface gap between neighbouring fills
  // Thin marks: a pair of bars never fills a wide day, it sits in its middle.
  const barW = Math.min(14, Math.max(1, (slot - gap * 3) / 2))
  const labelEvery = Math.ceil(days.length / 8)
  const y = (value) => pad.top + plotH - (value / top) * plotH

  return (
    <div className="relative">
      <svg ref={svgRef} viewBox={`0 0 ${width} ${height}`} className="max-h-72 w-full" role="img" aria-label="Messages and tool calls per day">
        {ticks.map((tick) => (
          <g key={tick}>
            <line x1={pad.left} x2={width - pad.right} y1={y(tick)} y2={y(tick)} className="stroke-border" strokeWidth="1" />
            <text x={pad.left - 6} y={y(tick)} dy="0.32em" textAnchor="end" className="fill-muted-foreground text-[10px]">
              {number(tick)}
            </text>
          </g>
        ))}
        {days.map((d, i) => {
          const x0 = pad.left + i * slot + (slot - (barW * 2 + gap)) / 2
          return (
            <g key={d.date}>
              {SERIES.map((series, j) => {
                const value = d[series.key]
                if (!value) return null
                const barH = (value / top) * plotH
                return <path key={series.key} d={barPath(x0 + j * (barW + gap), y(value), barW, barH)} className={series.className} />
              })}
              {i % labelEvery === 0 && (
                <text x={pad.left + (i + 0.5) * slot} y={height - 8} textAnchor="middle" className="fill-muted-foreground text-[10px]">
                  {day(d.date)}
                </text>
              )}
              {/* The hover target is the whole day, wider and taller than its bars. */}
              <rect
                x={pad.left + i * slot}
                y={pad.top}
                width={slot}
                height={plotH}
                fill="transparent"
                onMouseEnter={() => {
                  // The drawing keeps its proportions, so on a wide screen it is centred with
                  // margins: place the tooltip over the day itself, not over the full width.
                  const box = svgRef.current.getBoundingClientRect()
                  const scale = Math.min(box.width / width, box.height / height)
                  const offset = (box.width - width * scale) / 2
                  setHover({ index: i, left: Math.min(box.width - 170, offset + (pad.left + (i + 0.5) * slot) * scale) })
                }}
                onMouseLeave={() => setHover(null)}
              />
            </g>
          )
        })}
        {hover != null && (
          <rect
            x={pad.left + hover.index * slot}
            y={pad.top}
            width={slot}
            height={plotH}
            className="pointer-events-none fill-foreground/5"
          />
        )}
      </svg>
      {hover != null && (
        <div
          className="pointer-events-none absolute top-2 rounded-md border bg-popover px-3 py-2 text-xs shadow-md"
          style={{ left: Math.max(0, hover.left) }}
          role="status"
        >
          <p className="font-medium">{day(days[hover.index].date, { weekday: 'short', day: 'numeric', month: 'short' })}</p>
          {SERIES.map((series) => (
            <p key={series.key} className="flex items-center gap-1.5 text-muted-foreground">
              <span className={cn('size-2 rounded-sm', series.swatch)} aria-hidden="true" />
              {series.label} <span className="ml-auto pl-3 font-medium text-foreground tabular-nums">{number(days[hover.index][series.key])}</span>
            </p>
          ))}
        </div>
      )}
    </div>
  )
}

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

      <section className="rounded-md border bg-background p-4" aria-labelledby="activity-heading">
        <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
          <h2 id="activity-heading" className="text-sm font-semibold">Activity per day</h2>
          <ul className="flex items-center gap-4 text-xs text-muted-foreground" aria-label="Legend">
            {SERIES.map((series) => (
              <li key={series.key} className="flex items-center gap-1.5">
                <span className={cn('size-2.5 rounded-sm', series.swatch)} aria-hidden="true" />
                {series.label}
              </li>
            ))}
          </ul>
        </div>
        {quiet ? (
          <p className="py-10 text-center text-sm text-muted-foreground">No activity in this period yet.</p>
        ) : (
          <ActivityChart days={days} />
        )}
        <details className="mt-3 text-sm">
          <summary className="w-fit cursor-pointer rounded-sm text-xs text-muted-foreground outline-none hover:text-foreground focus-visible:ring-3 focus-visible:ring-ring/50">
            Show as a table
          </summary>
          <table className="mt-2 w-full text-left text-xs">
            <thead className="text-muted-foreground">
              <tr>
                <th className="py-1 font-medium">Day</th>
                <th className="py-1 text-right font-medium">Messages</th>
                <th className="py-1 text-right font-medium">Tool calls</th>
              </tr>
            </thead>
            <tbody>
              {days.map((d) => (
                <tr key={d.date} className="border-t">
                  <td className="py-1">{day(d.date, { weekday: 'short', day: 'numeric', month: 'short' })}</td>
                  <td className="py-1 text-right tabular-nums">{number(d.messages)}</td>
                  <td className="py-1 text-right tabular-nums">{number(d.tool_calls)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </details>
      </section>

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
                {tools.map((tool) => (
                  <tr key={tool.name} className="border-t">
                    <td className="px-4 py-2 font-mono text-xs">{tool.name}</td>
                    <td className="px-4 py-2 text-muted-foreground">
                      {TYPE_NAMES[tool.type] ?? tool.type}
                      {tool.app && ` · ${tool.app}`}
                    </td>
                    <td className="px-4 py-2 text-right tabular-nums">{number(tool.calls)}</td>
                    <td className={cn('px-4 py-2 text-right tabular-nums', tool.failures > 0 && 'text-destructive')}>{number(tool.failures)}</td>
                    <td className="hidden px-4 py-2 text-right tabular-nums sm:table-cell">{ms(tool.avg_ms)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>
      <p className="text-xs text-muted-foreground">New activity can take a minute to appear.</p>
    </div>
  )
}

export default function Analytics() {
  const { agentId } = useParams()
  const navigate = useNavigate()
  const agents = useAgents()
  const [range, setRange] = useState('7d')
  const analytics = useAnalytics(agentId, range)
  const list = agents.data ?? []

  // With no agent in the address, show the first one.
  const firstId = list[0]?.id
  useEffect(() => {
    if (!agentId && firstId) navigate(`/app/analytics/${firstId}`, { replace: true })
  }, [agentId, firstId, navigate])

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
    body = <Report data={analytics.data} />
  }

  return (
    <div className="flex flex-col gap-6 p-6">
      <div className="flex flex-wrap items-center justify-between gap-4">
        <h1 className="flex items-center gap-2 text-2xl font-semibold">
          <BarChart3 className="size-6 text-primary" aria-hidden="true" /> Analytics
        </h1>
        <div className="flex flex-wrap items-center gap-3">
          {list.length > 0 && (
            <AgentSelect agents={list} value={agentId} onChange={(id) => navigate(`/app/analytics/${id}`)} className="w-56" />
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
      {body}
    </div>
  )
}
