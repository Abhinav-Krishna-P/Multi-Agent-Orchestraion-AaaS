import { useRef, useState } from 'react'
import { cn } from '@/lib/utils'

// Validated with the dataviz palette checks (colour-blind separation and 3:1 contrast) on
// white and on the dark surface. Each series keeps its colour; text never takes it.
export const SERIES_COLORS = [
  { className: 'fill-[#2a78d6] dark:fill-[#3987e5]', swatch: 'bg-[#2a78d6] dark:bg-[#3987e5]' },
  { className: 'fill-[#eb6834] dark:fill-[#d95926]', swatch: 'bg-[#eb6834] dark:bg-[#d95926]' },
]

export const number = (value) => (value == null ? '–' : new Intl.NumberFormat().format(value))
export const day = (iso, options = { day: 'numeric', month: 'short' }) => new Date(`${iso}T00:00`).toLocaleDateString(undefined, options)
export const ms = (value) => (value == null ? '–' : value >= 1000 ? `${(value / 1000).toFixed(1)} s` : `${value} ms`)

export function Tile({ label, value, note }) {
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

/** `series` is two { key, label } entries, drawn in the two validated colours, in order. */
export function ActivityChart({ days, series, label }) {
  const [hover, setHover] = useState(null) // { index, left } with left in pixels from the chart's edge
  const svgRef = useRef(null)
  const width = 720
  const height = 220
  const pad = { top: 12, right: 8, bottom: 26, left: 34 }
  const plotW = width - pad.left - pad.right
  const plotH = height - pad.top - pad.bottom
  const peak = Math.max(1, ...days.flatMap((d) => series.map((s) => d[s.key])))
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
      <svg ref={svgRef} viewBox={`0 0 ${width} ${height}`} className="max-h-72 w-full" role="img" aria-label={label}>
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
              {series.map((s, j) => {
                const value = d[s.key]
                if (!value) return null
                const barH = (value / top) * plotH
                return <path key={s.key} d={barPath(x0 + j * (barW + gap), y(value), barW, barH)} className={SERIES_COLORS[j].className} />
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
          {series.map((s, j) => (
            <p key={s.key} className="flex items-center gap-1.5 text-muted-foreground">
              <span className={cn('size-2 rounded-sm', SERIES_COLORS[j].swatch)} aria-hidden="true" />
              {s.label} <span className="ml-auto pl-3 font-medium text-foreground tabular-nums">{number(days[hover.index][s.key])}</span>
            </p>
          ))}
        </div>
      )}
    </div>
  )
}

/** The chart's section: heading, legend, the chart or the empty text, and the table view. */
export function ActivitySection({ id, title, days, series, label, quiet, quietText }) {
  return (
    <section className="rounded-md border bg-background p-4" aria-labelledby={id}>
      <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
        <h2 id={id} className="text-sm font-semibold">{title}</h2>
        <ul className="flex items-center gap-4 text-xs text-muted-foreground" aria-label="Legend">
          {series.map((s, j) => (
            <li key={s.key} className="flex items-center gap-1.5">
              <span className={cn('size-2.5 rounded-sm', SERIES_COLORS[j].swatch)} aria-hidden="true" />
              {s.label}
            </li>
          ))}
        </ul>
      </div>
      {quiet ? (
        <p className="py-10 text-center text-sm text-muted-foreground">{quietText}</p>
      ) : (
        <ActivityChart days={days} series={series} label={label} />
      )}
      <details className="mt-3 text-sm">
        <summary className="w-fit cursor-pointer rounded-sm text-xs text-muted-foreground outline-none hover:text-foreground focus-visible:ring-3 focus-visible:ring-ring/50">
          Show as a table
        </summary>
        <table className="mt-2 w-full text-left text-xs">
          <thead className="text-muted-foreground">
            <tr>
              <th className="py-1 font-medium">Day</th>
              {series.map((s) => (
                <th key={s.key} className="py-1 text-right font-medium">{s.label}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {days.map((d) => (
              <tr key={d.date} className="border-t">
                <td className="py-1">{day(d.date, { weekday: 'short', day: 'numeric', month: 'short' })}</td>
                {series.map((s) => (
                  <td key={s.key} className="py-1 text-right tabular-nums">{number(d[s.key])}</td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </details>
    </section>
  )
}
