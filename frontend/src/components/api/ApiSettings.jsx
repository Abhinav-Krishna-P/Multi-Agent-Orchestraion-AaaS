import { useState } from 'react'
import { toast } from 'sonner'
import { ActionGroups } from '@/components/api/ActionGroups'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Switch } from '@/components/ui/switch'
import { useUpdateApiSettings } from '@/lib/queries'

export function ApiSettings({ agent, settings, actions }) {
  const update = useUpdateApiSettings(agent.id)
  const [rate, setRate] = useState(String(settings.calls_per_minute))
  const [seen, setSeen] = useState(settings.calls_per_minute)
  if (seen !== settings.calls_per_minute) {
    // Follow the saved value after a refetch.
    setSeen(settings.calls_per_minute)
    setRate(String(settings.calls_per_minute))
  }

  function save(body, done) {
    update.mutate(body, {
      onSuccess: () => toast.success(done),
      onError: (err) => {
        toast.error(err.message)
        setRate(String(settings.calls_per_minute))
      },
    })
  }

  function saveRate() {
    const n = Number(rate)
    if (!Number.isInteger(n) || n < 1 || n > 600) {
      toast.error('Calls per minute must be a whole number from 1 to 600.')
      return setRate(String(settings.calls_per_minute))
    }
    if (n !== settings.calls_per_minute) save({ calls_per_minute: n }, 'Limit saved.')
  }

  return (
    <section className="flex flex-col gap-4" aria-labelledby="api-settings-heading">
      <h2 id="api-settings-heading" className="text-lg font-semibold">
        Settings
      </h2>
      <div className="flex flex-col gap-4 rounded-xl border p-4">
        <div className="flex items-start gap-3">
          <Switch
            id="api-actions"
            checked={settings.actions}
            disabled={update.isPending}
            onCheckedChange={(checked) => save({ actions: checked }, checked ? 'Actions turned on.' : 'Actions turned off.')}
            className="mt-0.5"
          />
          <div className="min-w-0">
            <Label htmlFor="api-actions">Actions through the API</Label>
            <p className="mt-1 text-sm text-muted-foreground">Calls with a key run actions without asking.</p>
            {settings.actions && actions.length > 0 && (
              <ActionGroups actions={actions} className="mt-3" />
            )}
          </div>
        </div>
        <div className="flex flex-col gap-2">
          <Label htmlFor="api-rate">Calls per minute</Label>
          <Input
            id="api-rate"
            type="number"
            min={1}
            max={600}
            value={rate}
            onChange={(e) => setRate(e.target.value)}
            onBlur={saveRate}
            onKeyDown={(e) => e.key === 'Enter' && e.currentTarget.blur()}
            className="w-32"
          />
        </div>
      </div>
    </section>
  )
}
