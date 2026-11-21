import { Check, Loader2, X } from 'lucide-react'

/** One line per tool the agent used: a spinner while it runs, then a tick or a cross. */
export function ToolActivity({ tools }) {
  if (!tools?.length) return null
  return (
    <ul className="mb-2 flex flex-col gap-1 text-xs text-muted-foreground">
      {tools.map((tool, index) => (
        <li key={tool.id ?? index} className="flex items-center gap-1.5">
          {tool.ok === null || tool.ok === undefined ? (
            <Loader2 className="size-3.5 animate-spin" aria-hidden="true" />
          ) : tool.ok ? (
            <Check className="size-3.5 text-green-400" aria-hidden="true" />
          ) : (
            <X className="size-3.5 text-destructive" aria-hidden="true" />
          )}
          <span>{tool.label}</span>
          {/* Colour and icon are not the only signal: the outcome is also spelled out. */}
          <span className="sr-only">{tool.ok === null || tool.ok === undefined ? 'In progress' : tool.ok ? 'Done' : 'Failed'}</span>
          {tool.ok === false && <span className="text-destructive">Failed</span>}
        </li>
      ))}
    </ul>
  )
}
