import { ChevronRight } from 'lucide-react'
import { useState } from 'react'
import { groupActions, plural } from '@/components/api/actions'
import { cn } from '@/lib/utils'

/** One disclosure row per app; its actions show as small tags when opened. */
export function ActionGroups({ actions, className }) {
  const [open, setOpen] = useState(() => new Set())
  const toggle = (app) =>
    setOpen((prev) => {
      const next = new Set(prev)
      if (!next.delete(app)) next.add(app)
      return next
    })

  return (
    <ul className={cn('divide-y overflow-hidden rounded-lg border bg-muted/30', className)}>
      {groupActions(actions).map(({ app, names }) => {
        const isOpen = open.has(app)
        const panel = `actions-${app.replace(/\W+/g, '-')}`
        return (
          <li key={app}>
            <button
              type="button"
              aria-expanded={isOpen}
              aria-controls={panel}
              onClick={() => toggle(app)}
              className="flex w-full cursor-pointer items-center gap-2 px-3 py-2 text-left text-sm outline-none hover:bg-muted/60 focus-visible:ring-3 focus-visible:ring-ring/50 focus-visible:ring-inset"
            >
              <ChevronRight className={cn('size-4 shrink-0 text-muted-foreground transition-transform', isOpen && 'rotate-90')} aria-hidden="true" />
              <span className="font-medium">{app}</span>
              <span className="ml-auto rounded-full bg-secondary px-2 py-0.5 text-xs text-muted-foreground">{plural(names.length, 'action')}</span>
            </button>
            {isOpen && (
              <ul id={panel} className="flex flex-wrap gap-1.5 px-3 pt-1 pb-3 pl-9">
                {names.map((n) => (
                  <li key={n} className="rounded-md border bg-background px-2 py-0.5 text-xs text-muted-foreground">
                    {n}
                  </li>
                ))}
              </ul>
            )}
          </li>
        )
      })}
    </ul>
  )
}
