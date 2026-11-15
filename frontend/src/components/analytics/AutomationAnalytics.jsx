import { cn } from '@/lib/utils'
import { ActivitySection, Tile, day, ms, number } from './parts'

const SERIES = [
  { key: 'succeeded', label: 'Succeeded' },
  { key: 'failed', label: 'Failed' },
]
const STATUS_NAMES = { active: 'Active', paused: 'Paused', error: 'Needs attention', deleted: 'Deleted' }

export function AutomationReport({ data }) {
  const { totals, days, automations, active_now: activeNow } = data
  const quiet = totals.runs === 0 && days.every((d) => d.succeeded === 0 && d.failed === 0)
  const failed = totals.runs - totals.succeeded
  return (
    <div className="flex flex-col gap-5">
      <div className="grid grid-cols-2 gap-3 md:grid-cols-3 xl:grid-cols-5">
        <Tile label="Runs" value={number(totals.runs)} note={failed > 0 ? `${number(failed)} failed` : null} />
        <Tile label="Success rate" value={totals.success_rate == null ? '–' : `${Math.round(totals.success_rate * 100)}%`} />
        <Tile label="Active automations" value={number(activeNow)} />
        <Tile label="Created" value={number(totals.created)} />
        <Tile label="Test runs" value={number(totals.test_runs)} />
        <Tile label="Average run time" value={ms(totals.avg_run_ms)} />
        <Tile label="Tool calls by automations" value={number(totals.tool_calls)} />
      </div>

      <ActivitySection
        id="automation-activity-heading"
        title="Runs per day"
        days={days}
        series={SERIES}
        label="Succeeded and failed automation runs per day"
        quiet={quiet}
        quietText="No automation runs in this period."
      />

      <section className="rounded-md border bg-background" aria-labelledby="automations-heading">
        <h2 id="automations-heading" className="border-b px-4 py-3 text-sm font-semibold">Automations</h2>
        {automations.length === 0 ? (
          <p className="px-4 py-6 text-sm text-muted-foreground">No automation runs in this period.</p>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-left text-sm">
              <thead className="text-xs text-muted-foreground">
                <tr>
                  <th className="px-4 py-2 font-medium">Automation</th>
                  <th className="px-4 py-2 text-right font-medium">Runs</th>
                  <th className="px-4 py-2 text-right font-medium">Failed</th>
                  <th className="hidden px-4 py-2 text-right font-medium sm:table-cell">Test runs</th>
                  <th className="hidden px-4 py-2 text-right font-medium sm:table-cell">Average time</th>
                  <th className="hidden px-4 py-2 text-right font-medium md:table-cell">Last run</th>
                </tr>
              </thead>
              <tbody>
                {automations.map((a) => (
                  <tr key={a.id} className="border-t">
                    <td className="px-4 py-2">
                      {a.name}
                      <span className="ml-2 text-xs text-muted-foreground">{STATUS_NAMES[a.status] ?? a.status}</span>
                      {a.trigger_text && <span className="block text-xs text-muted-foreground">{a.trigger_text}</span>}
                    </td>
                    <td className="px-4 py-2 text-right tabular-nums">{number(a.runs)}</td>
                    <td className={cn('px-4 py-2 text-right tabular-nums', a.failures > 0 && 'text-destructive')}>{number(a.failures)}</td>
                    <td className="hidden px-4 py-2 text-right tabular-nums sm:table-cell">{number(a.test_runs)}</td>
                    <td className="hidden px-4 py-2 text-right tabular-nums sm:table-cell">{ms(a.avg_ms)}</td>
                    <td className="hidden px-4 py-2 text-right text-muted-foreground md:table-cell">
                      {a.last_run_at ? day(a.last_run_at.slice(0, 10)) : '–'}
                    </td>
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
