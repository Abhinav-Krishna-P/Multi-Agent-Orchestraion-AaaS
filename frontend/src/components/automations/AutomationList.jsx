import { CircleAlert, CircleCheck, CirclePause, FlaskConical, History, Loader2, MoreHorizontal, Plus, Trash2 } from 'lucide-react'
import { useState } from 'react'
import { toast } from 'sonner'
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
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu'
import { Sheet, SheetContent, SheetDescription, SheetHeader, SheetTitle } from '@/components/ui/sheet'
import { Skeleton } from '@/components/ui/skeleton'
import { Switch } from '@/components/ui/switch'
import { useAutomations, useDeleteAutomation, useSetAutomationStatus, useTestAutomation } from '@/lib/queries'
import { cn } from '@/lib/utils'
import { RunHistory, RunStatus, Time } from './RunHistory'
import { sameWords, triggerSummary } from './triggerSummary'

// Text, colour and icon together, so the status never relies on colour alone.
const STATUSES = {
  active: { label: 'Active', icon: CircleCheck, className: 'text-green-700' },
  paused: { label: 'Off', icon: CirclePause, className: 'text-muted-foreground' },
  error: { label: 'Needs attention', icon: CircleAlert, className: 'text-amber-700' },
}

function AutomationItem({ automation, agentId, agentLive }) {
  const setStatus = useSetAutomationStatus(agentId)
  const test = useTestAutomation(agentId)
  const remove = useDeleteAutomation(agentId)
  const [historyOpen, setHistoryOpen] = useState(false)
  const [confirming, setConfirming] = useState(false)
  const status = STATUSES[automation.status] ?? STATUSES.error
  const isOn = automation.status === 'active' // one that needs attention has stopped running; turning it on retries it
  // While the change is saved, the switch already shows where it is going.
  const checked = setStatus.isPending ? setStatus.variables.status === 'active' : isOn
  const running = automation.last_run?.status === 'running'
  const summary = triggerSummary(automation.trigger_kind, automation.trigger)
  const showNext = isOn && automation.trigger_kind !== 'event' && automation.next_run_at

  function runTest() {
    test.mutate(automation.id, {
      onSuccess: () => {
        toast.success('Test started')
        setHistoryOpen(true)
      },
      onError: (err) => toast.error(err.message),
    })
  }

  function toggle(on) {
    setStatus.mutate({ id: automation.id, status: on ? 'active' : 'paused' }, { onError: (err) => toast.error(err.message) })
  }

  function confirmDelete() {
    // mutateAsync, not mutate callbacks: on success this row is gone before they would run.
    remove.mutateAsync(automation.id).then(
      () => toast.success('Automation deleted'),
      (err) => {
        toast.error(err.message)
        setConfirming(false)
      },
    )
  }

  return (
    <li className="flex gap-3 p-4">
      <status.icon className={cn('mt-0.5 size-5 shrink-0', status.className)} aria-hidden="true" />
      <div className="flex min-w-0 flex-1 flex-col gap-3 md:flex-row md:items-start md:justify-between">
        <div className="flex min-w-0 flex-col gap-1">
          <div className="flex flex-wrap items-baseline gap-x-2 gap-y-0.5">
            <h2 className="min-w-0 font-semibold break-words">{automation.name}</h2>
            <span className={cn('text-xs font-medium', status.className)}>
              {status.label}
              {automation.status === 'error' && automation.status_reason && (
                <span className="font-normal"> · {automation.status_reason}</span>
              )}
            </span>
          </div>
          <p className="text-sm break-words text-muted-foreground">{summary}</p>
          {automation.trigger_text && !sameWords(automation.trigger_text, summary) && (
            <p className="text-xs break-words text-muted-foreground">{automation.trigger_text}</p>
          )}
          <p className="flex flex-wrap items-center gap-x-3 gap-y-1 text-xs text-muted-foreground">
            {showNext && (
              <span>
                Next run <Time iso={automation.next_run_at} />
              </span>
            )}
            {automation.last_run ? (
              <span className="inline-flex flex-wrap items-center gap-x-1.5">
                <span>
                  Last run <Time iso={automation.last_run.started_at} />
                </span>
                <span aria-hidden="true">·</span>
                <RunStatus status={automation.last_run.status} />
              </span>
            ) : (
              <span>Not run yet</span>
            )}
          </p>
          {running && (
            <p role="status" className="text-xs text-muted-foreground">
              A run is in progress
            </p>
          )}
        </div>

        <div className="flex shrink-0 flex-wrap items-center gap-3">
          <Button variant="outline" size="sm" onClick={runTest} disabled={!agentLive || test.isPending || running}>
            {test.isPending ? <Loader2 className="animate-spin" aria-hidden="true" /> : <FlaskConical aria-hidden="true" />}
            Test
          </Button>
          <Switch
            checked={checked}
            onCheckedChange={toggle}
            disabled={setStatus.isPending || (!isOn && !agentLive)}
            aria-label={automation.name}
          />
          <DropdownMenu>
            <DropdownMenuTrigger asChild>
              <Button variant="ghost" size="icon-sm" aria-label={`More actions for ${automation.name}`}>
                <MoreHorizontal aria-hidden="true" />
              </Button>
            </DropdownMenuTrigger>
            <DropdownMenuContent align="end" className="w-48">
              <DropdownMenuItem onSelect={() => setHistoryOpen(true)}>
                <History aria-hidden="true" /> View run history
              </DropdownMenuItem>
              <DropdownMenuSeparator />
              <DropdownMenuItem variant="destructive" onSelect={() => setConfirming(true)}>
                <Trash2 aria-hidden="true" /> Delete…
              </DropdownMenuItem>
            </DropdownMenuContent>
          </DropdownMenu>
        </div>
      </div>

      <Sheet open={historyOpen} onOpenChange={setHistoryOpen}>
        <SheetContent className="gap-0 data-[side=right]:w-full data-[side=right]:sm:max-w-lg">
          <SheetHeader className="border-b pr-12">
            <SheetTitle>Run history</SheetTitle>
            <SheetDescription className="break-words">{automation.name}</SheetDescription>
          </SheetHeader>
          {/* Mounted only while open, so it checks for new runs only then (every 2 seconds while one runs). */}
          <div className="min-h-0 flex-1 overflow-y-auto">
            <RunHistory automationId={automation.id} />
          </div>
        </SheetContent>
      </Sheet>

      <AlertDialog open={confirming} onOpenChange={(open) => !open && !remove.isPending && setConfirming(false)}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>Delete this automation?</AlertDialogTitle>
            <AlertDialogDescription>
              &ldquo;{automation.name}&rdquo; and its run history will be deleted. This can&apos;t be undone.
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel disabled={remove.isPending}>Keep it</AlertDialogCancel>
            <AlertDialogAction
              variant="destructive"
              disabled={remove.isPending}
              onClick={(event) => {
                event.preventDefault() // keep the dialog open until the delete finishes
                confirmDelete()
              }}
            >
              Delete automation
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </li>
  )
}

/** The selected agent's automations, each with Test, an on/off switch, and run history and Delete in its menu. */
export function AutomationList({ agent, onCreate }) {
  const automations = useAutomations(agent.id)
  const live = agent.status === 'live'

  if (automations.isPending) {
    return (
      <div className="flex flex-col gap-3" role="status" aria-label="Loading automations">
        <Skeleton className="h-24" />
        <Skeleton className="h-24" />
      </div>
    )
  }
  if (automations.isError) {
    return (
      <div className="flex flex-wrap items-center gap-3 rounded-xl border p-4">
        <p className="text-sm text-destructive">{automations.error.message}</p>
        <Button variant="outline" size="sm" onClick={() => automations.refetch()}>
          Retry
        </Button>
      </div>
    )
  }
  if (automations.data.length === 0) {
    return (
      <div className="flex flex-col items-center gap-3 rounded-xl border border-dashed px-6 py-12 text-center">
        <p className="font-medium">No automations yet</p>
        <p className="max-w-sm text-sm text-muted-foreground">
          {live
            ? `Describe a job in your own words, like a morning email or a reply when something arrives, and ${agent.name} will do it on its own.`
            : 'Deploy this agent to describe new automations.'}
        </p>
        {live && (
          <Button onClick={onCreate} className="mt-1">
            <Plus aria-hidden="true" /> Create automation
          </Button>
        )}
      </div>
    )
  }
  return (
    <ul className="divide-y rounded-xl border bg-background" aria-label={`${agent.name}'s automations`}>
      {automations.data.map((automation) => (
        <AutomationItem key={automation.id} automation={automation} agentId={agent.id} agentLive={live} />
      ))}
    </ul>
  )
}
