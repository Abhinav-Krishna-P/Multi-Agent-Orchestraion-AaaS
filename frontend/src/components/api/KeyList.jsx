import { Plus } from 'lucide-react'
import { useState } from 'react'
import { toast } from 'sonner'
import { CreateKeyDialog } from '@/components/api/CreateKeyDialog'
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
import { useRevokeApiKey } from '@/lib/queries'

const when = (iso) => new Date(iso).toLocaleDateString(undefined, { dateStyle: 'medium' })

export function KeyList({ agent, keys }) {
  const [creating, setCreating] = useState(false)
  const [revoking, setRevoking] = useState(null)
  const revoke = useRevokeApiKey(agent.id)

  function confirmRevoke() {
    revoke.mutate(revoking.id, {
      onSuccess: () => setRevoking(null),
      onError: (err) => toast.error(err.message),
    })
  }

  return (
    <section className="flex flex-col gap-3" aria-labelledby="api-keys-heading">
      <div className="flex items-center justify-between gap-3">
        <h2 id="api-keys-heading" className="text-lg font-semibold">
          Keys
        </h2>
        <Button size="sm" onClick={() => setCreating(true)}>
          <Plus aria-hidden="true" /> Create key
        </Button>
      </div>
      {keys.length === 0 ? (
        <p className="rounded-xl border border-dashed p-6 text-center text-sm text-muted-foreground">
          No keys yet. Create one to call this agent from your own program.
        </p>
      ) : (
        <ul className="flex flex-col divide-y rounded-xl border">
          {keys.map((key) => (
            <li key={key.id} className="flex flex-wrap items-center justify-between gap-3 p-3">
              <div className="min-w-0">
                <p className="truncate text-sm font-medium">{key.name}</p>
                <p className="text-xs text-muted-foreground">
                  <span className="font-mono">cap_…{key.hint}</span> · Created {when(key.created_at)} ·{' '}
                  {key.last_used_at ? `Last used ${when(key.last_used_at)}` : 'Never used'}
                </p>
              </div>
              <Button variant="outline" size="sm" onClick={() => setRevoking(key)} aria-label={`Revoke ${key.name}`}>
                Revoke
              </Button>
            </li>
          ))}
        </ul>
      )}

      {creating && <CreateKeyDialog agent={agent} open onOpenChange={setCreating} />}

      <AlertDialog open={Boolean(revoking)} onOpenChange={(open) => !open && !revoke.isPending && setRevoking(null)}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>Revoke this key?</AlertDialogTitle>
            <AlertDialogDescription>
              Revoke {revoking?.name}? Programs using it stop working at once. This can&apos;t be undone.
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel disabled={revoke.isPending}>Keep it</AlertDialogCancel>
            <AlertDialogAction
              variant="destructive"
              disabled={revoke.isPending}
              onClick={(event) => {
                event.preventDefault() // stay open until the revoke finishes
                confirmRevoke()
              }}
            >
              Revoke key
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </section>
  )
}
