import { Blocks, Check, CircleAlert, Loader2, ShieldCheck, X } from 'lucide-react'
import { useState } from 'react'
import { Button } from '@/components/ui/button'
import { CardImage } from './cards/shared'

const FOLD_AT = 240 // characters; longer details open on request

function asText(value) {
  if (value == null) return ''
  return typeof value === 'string' ? value : JSON.stringify(value, null, 2)
}

/** One detail the agent filled in. Always plain text: nothing in it is a link or loads anything. */
function Detail({ label, value }) {
  const text = asText(value)
  const [open, setOpen] = useState(false)
  const long = text.length > FOLD_AT || text.split('\n').length > 6
  return (
    <div className="min-w-0">
      <dt className="text-xs text-muted-foreground">{label}</dt>
      <dd className="mt-0.5 text-sm break-words whitespace-pre-wrap">
        {long && !open ? `${text.slice(0, FOLD_AT).trimEnd()}…` : text || <span className="text-muted-foreground">(empty)</span>}
        {long && (
          <button
            type="button"
            aria-expanded={open}
            onClick={() => setOpen(!open)}
            className="ml-1 cursor-pointer rounded-sm text-xs font-medium text-primary outline-none hover:underline focus-visible:ring-3 focus-visible:ring-ring/50"
          >
            {open ? 'Show less' : 'Show all'}
          </button>
        )}
      </dd>
    </div>
  )
}

function Outcome({ approval }) {
  const { status, outcome, reason } = approval
  if (status === 'approved' && outcome === 'done')
    return (
      <p className="flex items-center gap-1.5 text-sm text-green-700">
        <Check className="size-4" aria-hidden="true" /> Approved and done
      </p>
    )
  if (status === 'approved' && outcome === 'failed')
    return (
      <p className="flex items-start gap-1.5 text-sm text-destructive">
        <CircleAlert className="mt-0.5 size-4 shrink-0" aria-hidden="true" /> Approved, but it failed{reason ? `: ${reason}` : ''}
      </p>
    )
  if (status === 'approved')
    return (
      <p className="flex items-start gap-1.5 text-sm text-amber-700">
        <CircleAlert className="mt-0.5 size-4 shrink-0" aria-hidden="true" />
        {outcome === 'unknown' && reason
          ? `Approved, but ${reason.charAt(0).toLowerCase()}${reason.slice(1)}`
          : `Approved, but it isn't known whether it was done. Check ${approval.app_name} before trying again.`}
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

/**
 * An action the agent wants to take that changes something. Nothing has happened yet: it
 * runs only if the user approves it here, exactly as shown.
 */
export function ApprovalCard({ approval, active, disabled, onDecide }) {
  const [choice, setChoice] = useState(null) // the button pressed, while its answer is sent
  const pending = approval.status === 'pending'
  const args = approval.arguments ?? {}
  // In the action's own order (the server keeps it; the database does not keep key order).
  const names = (approval.order ?? Object.keys(args)).filter((name) => name in args)

  function decide(decision) {
    setChoice(decision)
    onDecide(decision)
  }

  return (
    <section className="mt-3 rounded-xl border bg-background" aria-label={`Approval: ${approval.action_name}`}>
      <header className="flex items-center gap-3 border-b px-4 py-3">
        <span className="flex size-8 shrink-0 items-center justify-center">
          <CardImage
            src={approval.logo}
            className="size-7 object-contain"
            fallback={<Blocks className="size-5 text-primary" aria-hidden="true" />}
          />
        </span>
        <div className="min-w-0 flex-1">
          <p className="truncate text-sm font-semibold">{approval.action_name}</p>
          <p className="text-xs text-muted-foreground">{approval.app_name}</p>
        </div>
        {pending && (
          <span className="flex items-center gap-1 text-xs font-medium text-amber-700">
            <ShieldCheck className="size-3.5" aria-hidden="true" /> Needs your approval
          </span>
        )}
      </header>

      {names.length === 0 ? (
        <p className="px-4 py-3 text-sm text-muted-foreground">No details.</p>
      ) : (
        <dl className="flex flex-col gap-3 px-4 py-3">
          {names.map((name) => (
            <Detail key={name} label={approval.labels?.[name] ?? name} value={args[name]} />
          ))}
        </dl>
      )}

      <footer className="flex flex-wrap items-center justify-between gap-3 border-t px-4 py-3">
        {pending && active ? (
          <>
            <p className="text-xs text-muted-foreground">Nothing has been done yet.</p>
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
          // The answer is on its way; an approved action runs before the agent replies.
          <p className="flex items-center gap-1.5 text-sm text-muted-foreground" role="status">
            <Loader2 className="size-4 animate-spin" aria-hidden="true" />
            {choice === 'approve' ? `Approved. Running it in ${approval.app_name}…` : 'Declined. Telling the agent…'}
          </p>
        ) : (
          <Outcome approval={approval} />
        )}
      </footer>
    </section>
  )
}
