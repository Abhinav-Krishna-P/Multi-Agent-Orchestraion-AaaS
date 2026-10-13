import { MoreHorizontal, Trash2 } from 'lucide-react'
import { Link } from 'react-router-dom'
import { Button } from '@/components/ui/button'
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu'
import { Skeleton } from '@/components/ui/skeleton'
import { cn } from '@/lib/utils'

const DAY = 24 * 60 * 60 * 1000

/** Groups chats under Today, Yesterday, or their date, keeping the newest-first order. */
function groupByDate(sessions) {
  const startOfToday = new Date().setHours(0, 0, 0, 0)
  const groups = []
  for (const session of sessions) {
    const time = new Date(session.last_message_at).getTime()
    let label
    if (time >= startOfToday) label = 'Today'
    else if (time >= startOfToday - DAY) label = 'Yesterday'
    else label = new Date(time).toLocaleDateString(undefined, { day: 'numeric', month: 'short', year: 'numeric' })
    const last = groups[groups.length - 1]
    if (last?.label === label) last.sessions.push(session)
    else groups.push({ label, sessions: [session] })
  }
  return groups
}

export function SessionList({ agentId, sessions, activeId, onDelete, onNavigate }) {
  if (sessions.isPending) {
    return (
      <div className="flex flex-col gap-2 p-1" role="status" aria-label="Loading chats">
        <Skeleton className="h-8" />
        <Skeleton className="h-8" />
        <Skeleton className="h-8" />
      </div>
    )
  }
  if (sessions.isError) {
    return (
      <div className="flex flex-col items-start gap-2 p-2">
        <p className="text-sm text-destructive">Your chats couldn&apos;t load.</p>
        <Button variant="outline" size="sm" onClick={() => sessions.refetch()}>
          Retry
        </Button>
      </div>
    )
  }
  if (sessions.data.length === 0) {
    return <p className="p-2 text-sm text-muted-foreground">No chats yet. Send a message to start one.</p>
  }

  return (
    <nav aria-label="Chats" className="flex flex-col gap-3">
      {groupByDate(sessions.data).map((group) => (
        <div key={group.label}>
          <h3 className="px-2 pb-1 text-xs font-medium text-muted-foreground">{group.label}</h3>
          <ul className="flex flex-col gap-0.5">
            {group.sessions.map((session) => {
              const active = session.id === activeId
              return (
                <li
                  key={session.id}
                  className={cn(
                    'group/row flex items-center rounded-lg',
                    active ? 'bg-primary/10 text-primary' : 'hover:bg-muted',
                  )}
                >
                  <Link
                    to={`/app/chat/${agentId}/${session.id}`}
                    onClick={onNavigate}
                    aria-current={active ? 'page' : undefined}
                    className="min-w-0 flex-1 truncate rounded-lg px-2 py-1.5 text-sm outline-none focus-visible:ring-3 focus-visible:ring-ring/50"
                  >
                    {session.title}
                  </Link>
                  <DropdownMenu>
                    <DropdownMenuTrigger asChild>
                      <Button
                        variant="ghost"
                        size="icon-sm"
                        aria-label={`More actions for ${session.title}`}
                        className="mr-0.5 opacity-0 group-hover/row:opacity-100 focus-visible:opacity-100 aria-expanded:opacity-100"
                      >
                        <MoreHorizontal aria-hidden="true" />
                      </Button>
                    </DropdownMenuTrigger>
                    <DropdownMenuContent align="start">
                      <DropdownMenuItem variant="destructive" onSelect={() => onDelete(session)}>
                        <Trash2 aria-hidden="true" /> Delete
                      </DropdownMenuItem>
                    </DropdownMenuContent>
                  </DropdownMenu>
                </li>
              )
            })}
          </ul>
        </div>
      ))}
    </nav>
  )
}
