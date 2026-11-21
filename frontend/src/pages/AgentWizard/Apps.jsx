import { Blocks, Loader2, Search, TriangleAlert } from 'lucide-react'
import { useState } from 'react'
import { toast } from 'sonner'
import { CardImage } from '@/components/chat/cards/shared'
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from '@/components/ui/alert-dialog'
import { Button } from '@/components/ui/button'
import { Checkbox } from '@/components/ui/checkbox'
import { Input } from '@/components/ui/input'
import { Popover, PopoverContent, PopoverTrigger } from '@/components/ui/popover'
import { Skeleton } from '@/components/ui/skeleton'
import { useAppSignIn, useCheckAppsOnOpen } from '@/lib/appSignIn'
import { useDisconnectApp, useIntegrations, useSetAppActions } from '@/lib/queries'
import { StepFooter } from './StepFooter'

const ACTION_GROUPS = [
  { kind: 'read', title: 'Reads', note: 'Run straight away. They only look things up.' },
  { kind: 'write', title: 'Changes things', note: 'The agent asks you before each one, showing exactly what it will do.' },
]

const STATUS_LINES = {
  none: 'Not connected',
  pending: 'Finish signing in, then come back here',
  expired: 'Reconnect needed',
}

function AppCard({ app, busy, onConnect, onRefresh, onToggleAction, onDisconnect }) {
  const on = app.actions.filter((action) => action.on).length
  return (
    <div className="flex flex-col gap-3 rounded-md border bg-background p-4 transition-colors hover:border-foreground/25">
      <div className="flex items-center gap-3">
        <span className="flex size-10 shrink-0 items-center justify-center overflow-hidden rounded-md">
          <CardImage
            src={app.logo}
            className="size-9 object-contain"
            fallback={<Blocks className="size-5 text-primary" aria-hidden="true" />}
          />
        </span>
        <div className="min-w-0 flex-1">
          <p className="truncate text-sm font-semibold">{app.name}</p>
          <p
            className={
              app.status === 'expired'
                ? 'flex items-center gap-1 text-xs text-destructive'
                : app.status === 'active'
                  ? 'text-xs text-green-400'
                  : 'text-xs text-muted-foreground'
            }
          >
            {app.status === 'expired' && <TriangleAlert className="size-3.5" aria-hidden="true" />}
            {app.status === 'active' ? `Connected · ${on} of ${app.actions.length} actions on` : STATUS_LINES[app.status]}
          </p>
        </div>
      </div>

      <div className="flex flex-wrap items-center justify-end gap-2">
        {busy && <Loader2 className="size-4 animate-spin text-muted-foreground" aria-hidden="true" />}
        {app.status === 'none' && (
          <Button type="button" size="sm" disabled={busy} onClick={onConnect}>
            Connect
          </Button>
        )}
        {app.status === 'pending' && (
          <>
            <Button type="button" variant="ghost" size="sm" disabled={busy} onClick={onDisconnect}>
              Cancel
            </Button>
            <Button type="button" variant="outline" size="sm" disabled={busy} onClick={onRefresh}>
              Check again
            </Button>
          </>
        )}
        {app.status === 'expired' && (
          <>
            <Button type="button" variant="ghost" size="sm" disabled={busy} onClick={onDisconnect}>
              Disconnect
            </Button>
            <Button type="button" size="sm" disabled={busy} onClick={onConnect}>
              Reconnect
            </Button>
          </>
        )}
        {app.status === 'active' && (
          <>
            <Button type="button" variant="ghost" size="sm" disabled={busy} onClick={onDisconnect}>
              Disconnect
            </Button>
            <Popover>
              <PopoverTrigger asChild>
                <Button type="button" variant="outline" size="sm" aria-label={`Choose ${app.name} actions`}>
                  Actions
                </Button>
              </PopoverTrigger>
              <PopoverContent align="end" className="max-h-80 w-80 overflow-y-auto">
                <p className="mb-3 text-sm font-medium">What may the agent do in {app.name}?</p>
                {app.actions.length === 0 ? (
                  <p className="text-sm text-muted-foreground">This app has no actions yet.</p>
                ) : (
                  ACTION_GROUPS.map((group) => {
                    const actions = app.actions.filter((action) => action.kind === group.kind)
                    if (actions.length === 0) return null
                    return (
                      <fieldset key={group.kind} className="mb-4 last:mb-0">
                        <legend className="text-xs font-semibold tracking-wide text-muted-foreground uppercase">{group.title}</legend>
                        <p className="mb-2 text-xs text-muted-foreground">{group.note}</p>
                        <div className="flex flex-col gap-3">
                          {actions.map((action) => (
                            <div key={action.slug} className="flex items-start gap-2">
                              <Checkbox
                                id={`action-${action.slug}`}
                                checked={action.on}
                                disabled={busy}
                                onCheckedChange={(checked) => onToggleAction(action.slug, checked === true)}
                                className="mt-0.5"
                              />
                              <label htmlFor={`action-${action.slug}`} className="cursor-pointer text-sm">
                                {action.name}
                                <span className="line-clamp-2 text-xs text-muted-foreground">{action.description}</span>
                              </label>
                            </div>
                          ))}
                        </div>
                      </fieldset>
                    )
                  })
                )}
              </PopoverContent>
            </Popover>
          </>
        )}
      </div>
    </div>
  )
}

export default function Apps({ agent, onNext, onBack }) {
  const integrations = useIntegrations(agent.id)
  const setActions = useSetAppActions(agent.id)
  const disconnect = useDisconnectApp(agent.id)
  const [query, setQuery] = useState('')
  const [toDisconnect, setToDisconnect] = useState(null)

  const apps = integrations.data?.apps ?? []
  const { connect, refresh, startConnect } = useAppSignIn(agent.id, apps)
  useCheckAppsOnOpen(agent.id) // a connection that broke since last time shows Reconnect

  function toggleAction(app, slug, on) {
    const chosen = app.actions.filter((action) => (action.slug === slug ? on : action.on)).map((action) => action.slug)
    setActions.mutate({ app: app.app, actions: chosen }, { onError: (error) => toast.error(error.message) })
  }

  const busyApp = (app) =>
    [connect, refresh, setActions, disconnect].some(
      (mutation) => mutation.isPending && (mutation.variables?.app ?? mutation.variables) === app.app,
    )

  const heading = (
    <div>
      <h2 className="text-lg font-semibold">Connect your apps</h2>
      <p className="mt-1 text-sm text-muted-foreground">
        Sign in to the apps this agent may use. A connection belongs to this agent only. You choose what it may do, and
        it asks you before anything that sends, creates or changes.
      </p>
    </div>
  )

  let body
  if (integrations.isPending) {
    body = (
      <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-3" role="status" aria-label="Loading apps">
        {Array.from({ length: 6 }, (_, i) => (
          <Skeleton key={i} className="h-28" />
        ))}
      </div>
    )
  } else if (integrations.isError) {
    body = (
      <div className="flex flex-col items-start gap-3 rounded-xl border p-6">
        <p className="text-sm text-destructive">The apps couldn&apos;t load.</p>
        <Button type="button" variant="outline" onClick={() => integrations.refetch()}>
          Retry
        </Button>
      </div>
    )
  } else if (!integrations.data.enabled) {
    body = (
      <p className="rounded-xl border border-dashed p-10 text-center text-sm text-muted-foreground">
        App connections aren&apos;t set up on this server yet. You can continue without them.
      </p>
    )
  } else {
    const shown = apps.filter((app) => `${app.name} ${app.category}`.toLowerCase().includes(query.trim().toLowerCase()))
    const categories = [...new Set(apps.map((app) => app.category))]
    body = (
      <>
        <div className="relative">
          <Search className="pointer-events-none absolute top-1/2 left-2.5 size-4 -translate-y-1/2 text-muted-foreground" aria-hidden="true" />
          <Input
            type="search"
            value={query}
            onChange={(event) => setQuery(event.target.value)}
            placeholder="Search apps"
            aria-label="Search apps"
            className="pl-8"
          />
        </div>
        {shown.length === 0 ? (
          <div className="flex flex-col items-center gap-3 rounded-xl border border-dashed p-10 text-center">
            <p className="text-sm text-muted-foreground">No apps match.</p>
            <Button type="button" variant="outline" onClick={() => setQuery('')}>
              Show all apps
            </Button>
          </div>
        ) : (
          categories
            .filter((name) => shown.some((app) => app.category === name))
            .map((name) => (
              <section key={name} aria-labelledby={`apps-${name}`} className="flex flex-col gap-3">
                <h3 id={`apps-${name}`} className="text-base font-semibold">
                  {name}
                </h3>
                <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-3">
                  {shown
                    .filter((app) => app.category === name)
                    .map((app) => (
                      <AppCard
                        key={app.app}
                        app={app}
                        busy={busyApp(app)}
                        onConnect={() => startConnect(app)}
                        onRefresh={() => refresh.mutate(app.app)}
                        onToggleAction={(slug, on) => toggleAction(app, slug, on)}
                        onDisconnect={() => setToDisconnect(app)}
                      />
                    ))}
                </div>
              </section>
            ))
        )}
      </>
    )
  }

  return (
    <form
      onSubmit={(event) => {
        event.preventDefault()
        onNext()
      }}
      className="flex flex-col gap-5"
    >
      {heading}
      {body}

      <AlertDialog open={Boolean(toDisconnect)} onOpenChange={(open) => !open && setToDisconnect(null)}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>Disconnect {toDisconnect?.name}?</AlertDialogTitle>
            <AlertDialogDescription>
              This agent will no longer be able to use {toDisconnect?.name}. You can connect it again later.
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>Keep connected</AlertDialogCancel>
            <AlertDialogAction
              variant="destructive"
              onClick={() => {
                disconnect.mutate(toDisconnect.app, { onError: (error) => toast.error(error.message) })
                setToDisconnect(null)
              }}
            >
              Disconnect
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>

      <StepFooter onBack={onBack} />
    </form>
  )
}
