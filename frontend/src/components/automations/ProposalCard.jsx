import { Check, CircleAlert, Loader2, ShieldCheck, Workflow, X } from 'lucide-react'
import { useState } from 'react'
import { Button } from '@/components/ui/button'
import { sameWords, triggerSummary } from './triggerSummary'

const asText = (value) => (typeof value === 'string' ? value : JSON.stringify(value))

function Outcome({ approval }) {
  const { status, outcome, reason } = approval
  if (status === 'approved' && outcome === 'failed')
    return (
      <p className="flex items-start gap-1.5 text-sm text-destructive">
        <CircleAlert className="mt-0.5 size-4 shrink-0" aria-hidden="true" /> Approved, but it couldn&apos;t be set up
        {reason ? `: ${reason}` : ''}
      </p>
    )
  if (status === 'approved')
    return (
      <p className="flex items-center gap-1.5 text-sm text-green-700">
        <Check className="size-4" aria-hidden="true" /> Automation is live
      </p>
    )
  if (status === 'rejected')
    return (
      <p className="flex items-center gap-1.5 text-sm text-muted-foreground">
        <X className="size-4" aria-hidden="true" /> Declined
      </p>
    )
  if (status === 'skipped') return <p className="text-sm text-muted-foreground">Not approved</p>
  return <p className="text-sm text-muted-foreground">Waiting for approval</p>
}

function Field({ label, children }) {
  return (
    <div className="min-w-0">
      <dt className="text-xs text-muted-foreground">{label}</dt>
      <dd className="mt-0.5 text-sm break-words whitespace-pre-wrap">{children}</dd>
    </div>
  )
}

/** The automation the describe agent wants to create. Nothing exists until the user approves it here. */
export function ProposalCard({ approval, active, disabled, onDecide }) {
  const [choice, setChoice] = useState(null) // the button pressed, while its answer is sent
  const pending = approval.status === 'pending'
  const summary = triggerSummary(approval.trigger_kind, approval.trigger, approval.timezone)
  const label = (tool) => approval.tool_labels?.[tool] ?? tool
  const locked = Object.entries(approval.locked ?? {}).flatMap(([tool, args]) =>
    Object.entries(args ?? {}).map(([arg, value]) => ({ tool, arg, value })),
  )

  function decide(decision) {
    setChoice(decision)
    onDecide(decision)
  }

  return (
    <section className="mt-3 rounded-xl border bg-background" aria-label={`Automation: ${approval.name}`}>
      <header className="flex flex-wrap items-center gap-3 border-b px-4 py-3">
        <Workflow className="size-5 shrink-0 text-primary" aria-hidden="true" />
        <div className="min-w-0 flex-1">
          <p className="text-sm font-semibold break-words">{approval.name}</p>
          {/* The settings that will actually run (the chat's zone for a cron), not only the model's wording. */}
          <p className="text-xs break-words text-muted-foreground">{summary}</p>
          {!sameWords(approval.trigger_text, summary) && <p className="text-xs text-muted-foreground">{approval.trigger_text}</p>}
        </div>
        {pending && (
          <span className="flex items-center gap-1 text-xs font-medium text-amber-700">
            <ShieldCheck className="size-3.5" aria-hidden="true" /> Needs your approval
          </span>
        )}
      </header>

      <dl className="flex flex-col gap-3 px-4 py-3">
        <Field label="What it does">{approval.task}</Field>
        <Field label="Tools it may use">{(approval.tools ?? []).map(label).join(', ') || 'None'}</Field>
        {locked.length > 0 && (
          <Field label="Always uses">
            <ul className="flex flex-col gap-0.5">
              {locked.map(({ tool, arg, value }) => (
                <li key={`${tool}.${arg}`}>
                  <span className="text-muted-foreground">
                    {label(tool)} · {arg}:
                  </span>{' '}
                  {asText(value)}
                </li>
              ))}
            </ul>
          </Field>
        )}
      </dl>

      <footer className="flex flex-wrap items-center justify-between gap-3 border-t px-4 py-3">
        {pending && active ? (
          <>
            <p className="text-xs text-muted-foreground">Once approved, it runs on its own without asking.</p>
            <div className="flex items-center gap-2">
              <Button type="button" variant="outline" size="sm" disabled={disabled} onClick={() => decide('reject')}>
                {disabled && choice === 'reject' && <Loader2 className="animate-spin" aria-hidden="true" />}
                Reject
              </Button>
              <Button type="button" size="sm" disabled={disabled} onClick={() => decide('approve')}>
                {disabled && choice === 'approve' && <Loader2 className="animate-spin" aria-hidden="true" />}
                Approve
              </Button>
            </div>
          </>
        ) : pending && choice ? (
          <p className="flex items-center gap-1.5 text-sm text-muted-foreground" role="status">
            <Loader2 className="size-4 animate-spin" aria-hidden="true" />
            {choice === 'approve' ? 'Approved. Setting it up…' : 'Declined. Telling the agent…'}
          </p>
        ) : (
          <Outcome approval={approval} />
        )}
      </footer>
    </section>
  )
}
