import { Blocks, Loader2, TriangleAlert } from 'lucide-react'
import { CardImage } from '@/components/chat/cards/shared'
import { Button } from '@/components/ui/button'
import { useAppSignIn, useCheckAppsOnOpen } from '@/lib/appSignIn'
import { useIntegrations } from '@/lib/queries'

/**
 * Above the message box: one line per app whose connection has stopped working, with a
 * Reconnect button, so the user can fix it without leaving the chat.
 */
export function ReconnectBar({ agentId }) {
  useCheckAppsOnOpen(agentId)
  const integrations = useIntegrations(agentId)
  const apps = integrations.data?.apps ?? []
  const { connect, refresh, startConnect } = useAppSignIn(agentId, apps)
  const broken = apps.filter((app) => app.status === 'expired' || app.status === 'pending')
  if (broken.length === 0) return null

  const busy = (app) =>
    (connect.isPending && connect.variables === app.app) || (refresh.isPending && refresh.variables === app.app)

  return (
    <ul className="flex flex-col gap-2 border-b px-4 py-2" aria-label="Apps that need attention">
      {broken.map((app) => (
        <li key={app.app} className="flex flex-wrap items-center gap-x-3 gap-y-1 text-sm">
          <span className="flex size-6 shrink-0 items-center justify-center">
            <CardImage
              src={app.logo}
              className="size-5 object-contain"
              fallback={<Blocks className="size-4 text-primary" aria-hidden="true" />}
            />
          </span>
          <span className="flex min-w-0 flex-1 items-center gap-1.5">
            {app.status === 'expired' && <TriangleAlert className="size-4 shrink-0 text-destructive" aria-hidden="true" />}
            {app.status === 'expired'
              ? `${app.name} needs reconnecting. The agent can't use it until you do.`
              : `Finish signing in to ${app.name}, then come back here.`}
          </span>
          {busy(app) && <Loader2 className="size-4 animate-spin text-muted-foreground" aria-hidden="true" />}
          {app.status === 'expired' ? (
            <Button type="button" size="sm" disabled={busy(app)} onClick={() => startConnect(app)}>
              Reconnect {app.name}
            </Button>
          ) : (
            <Button type="button" size="sm" variant="outline" disabled={busy(app)} onClick={() => refresh.mutate(app.app)}>
              Check again
            </Button>
          )}
        </li>
      ))}
    </ul>
  )
}
