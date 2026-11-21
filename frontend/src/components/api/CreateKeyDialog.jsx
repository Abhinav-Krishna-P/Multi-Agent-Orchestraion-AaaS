import { Check, ChevronRight, Copy, Loader2 } from 'lucide-react'
import { useState } from 'react'
import { toast } from 'sonner'
import { actionSummary } from '@/components/api/actions'
import { ActionGroups } from '@/components/api/ActionGroups'
import { Button } from '@/components/ui/button'
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from '@/components/ui/dialog'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { useAgentApi, useCreateApiKey } from '@/lib/queries'

/** The new key lives only in this component's state. The parent mounts the dialog only while open, so any close unmounts it and drops the key. */
export function CreateKeyDialog({ agent, open, onOpenChange }) {
  const info = useAgentApi(agent.id)
  const create = useCreateApiKey(agent.id)
  const [name, setName] = useState('')
  const [created, setCreated] = useState(null)
  const [copied, setCopied] = useState(false)
  const [seeActions, setSeeActions] = useState(false)
  const actions = info.data?.actions ?? []
  const actionsOn = info.data?.settings.actions !== false
  const trimmed = name.trim()

  function submit(event) {
    event.preventDefault()
    if (!trimmed || create.isPending) return
    create.mutate(trimmed, { onSuccess: setCreated })
  }

  async function copy() {
    try {
      await navigator.clipboard.writeText(created.key)
      setCopied(true)
    } catch {
      toast.error("Couldn't copy. Select the key and copy it by hand.")
    }
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-lg">
        {created ? (
          <>
            <DialogHeader>
              <DialogTitle>Key created</DialogTitle>
              <DialogDescription>You won&apos;t see this key again. Keep it secret, like a password.</DialogDescription>
            </DialogHeader>
            <div className="flex items-center gap-2">
              <Input readOnly value={created.key} aria-label="Your new API key" onFocus={(e) => e.target.select()} className="font-mono" />
              <Button variant="outline" onClick={copy}>
                {copied ? <Check aria-hidden="true" /> : <Copy aria-hidden="true" />}
                {copied ? 'Copied' : 'Copy'}
              </Button>
            </div>
            <DialogFooter>
              <Button onClick={() => onOpenChange(false)}>Done</Button>
            </DialogFooter>
          </>
        ) : (
          <form onSubmit={submit} className="flex flex-col gap-4">
            <DialogHeader>
              <DialogTitle>Create a key</DialogTitle>
              <DialogDescription>
                {!actionsOn
                  ? "Actions through the API are off: calls with this key can't send, create or change anything in connected apps."
                  : actions.length > 0
                  ? `Calls with this key run the agent's actions automatically, without asking: it can run ${actionSummary(actions)}.`
                  : 'This agent has no actions right now; any you add later run automatically too.'}
              </DialogDescription>
            </DialogHeader>
            {actionsOn && actions.length > 0 && (
              <div className="flex flex-col gap-2">
                <button
                  type="button"
                  aria-expanded={seeActions}
                  aria-controls="api-key-actions"
                  onClick={() => setSeeActions((v) => !v)}
                  className="inline-flex w-fit cursor-pointer items-center gap-1 rounded-sm text-sm font-medium text-primary outline-none hover:underline focus-visible:ring-3 focus-visible:ring-ring/50"
                >
                  <ChevronRight className={`size-4 transition-transform ${seeActions ? 'rotate-90' : ''}`} aria-hidden="true" />
                  {seeActions ? 'Hide actions' : 'See actions'}
                </button>
                {seeActions && (
                  <div id="api-key-actions" className="max-h-60 overflow-y-auto">
                    <ActionGroups actions={actions} />
                  </div>
                )}
              </div>
            )}
            <div className="flex flex-col gap-2">
              <Label htmlFor="api-key-name">Name</Label>
              <Input
                id="api-key-name"
                value={name}
                onChange={(e) => setName(e.target.value)}
                maxLength={60}
                placeholder="For example, my website"
                autoComplete="off"
                autoFocus
              />
              {create.isError && (
                <p role="alert" className="text-sm text-destructive">
                  {create.error.message}
                </p>
              )}
            </div>
            <DialogFooter>
              <Button type="submit" disabled={!trimmed || create.isPending}>
                {create.isPending && <Loader2 className="animate-spin" aria-hidden="true" />}
                Create
              </Button>
            </DialogFooter>
          </form>
        )}
      </DialogContent>
    </Dialog>
  )
}
