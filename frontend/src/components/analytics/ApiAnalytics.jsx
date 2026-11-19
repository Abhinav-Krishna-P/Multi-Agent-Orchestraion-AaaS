import { ActivitySection, Tile, ms, number } from './parts'

const SERIES = [
  { key: 'succeeded', label: 'Succeeded' },
  { key: 'failed', label: 'Failed' },
]

export function ApiReport({ data }) {
  const { totals, days } = data
  const quiet = totals.calls === 0 && days.every((d) => d.succeeded === 0 && d.failed === 0)
  const failed = totals.calls - totals.succeeded
  return (
    <div className="flex flex-col gap-5">
      <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
        <Tile label="Calls" value={number(totals.calls)} note={failed > 0 ? `${number(failed)} failed` : null} />
        <Tile label="Success rate" value={totals.success_rate == null ? '–' : `${Math.round(totals.success_rate * 100)}%`} />
        <Tile label="Average time" value={ms(totals.avg_call_ms)} />
        <Tile label="Tool calls" value={number(totals.tool_calls)} />
      </div>

      <ActivitySection
        id="api-activity-heading"
        title="Calls per day"
        days={days}
        series={SERIES}
        label="Succeeded and failed API calls per day"
        quiet={quiet}
        quietText="No API calls in this period yet."
      />
      <p className="text-xs text-muted-foreground">New activity can take a minute to appear.</p>
    </div>
  )
}
