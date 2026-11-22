import { Loader2 } from 'lucide-react'
import { useId, useState } from 'react'
import { toast } from 'sonner'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { useDeleteLlmKey, useSaveLlmKey } from '@/lib/queries'

/**
 * One provider's key: an input when none is saved, otherwise only a hint with
 * Replace and Remove. The full key is never shown again after saving.
 */
export function ApiKeyField({ provider, providerName, savedKey, showLabel = true }) {
  const inputId = useId()
  const [value, setValue] = useState('')
  const [replacing, setReplacing] = useState(false)
  const [error, setError] = useState(null)
  const save = useSaveLlmKey()
  const remove = useDeleteLlmKey()

  const editing = !savedKey || replacing

  function submit(event) {
    event.preventDefault()
    const apiKey = value.trim()
    if (!apiKey) return
    setError(null)
    save.mutate(
      { provider, apiKey },
      {
        onSuccess: () => {
          setValue('')
          setReplacing(false)
          toast.success('Key saved')
        },
        onError: (err) =>
          setError(err.code === 'invalid_api_key' ? "This key didn't work. Check it and try again." : err.message),
      },
    )
  }

  function removeKey() {
    setError(null)
    remove.mutate(provider, {
      onSuccess: () => toast.success('Key removed'),
      onError: (err) => setError(err.message),
    })
  }

  return (
    <div className="flex flex-col gap-2">
      {showLabel && <Label htmlFor={editing ? inputId : undefined}>{providerName}</Label>}

      {editing ? (
        <form onSubmit={submit} className="flex gap-2">
          <Input
            id={inputId}
            type="password"
            autoComplete="off"
            placeholder={`Paste your ${providerName} API key`}
            aria-label={showLabel ? undefined : `${providerName} API key`}
            aria-invalid={error ? true : undefined}
            value={value}
            onChange={(event) => setValue(event.target.value)}
            disabled={save.isPending}
          />
          <Button type="submit" disabled={save.isPending || !value.trim()}>
            {save.isPending && <Loader2 className="animate-spin" aria-hidden="true" />}
            Save key
          </Button>
          {replacing && (
            <Button
              type="button"
              variant="ghost"
              disabled={save.isPending}
              onClick={() => {
                setReplacing(false)
                setValue('')
                setError(null)
              }}
            >
              Cancel
            </Button>
          )}
        </form>
      ) : (
        <div className="flex items-center gap-2">
          <span className="flex-1 font-mono text-sm text-muted-foreground" aria-label={`Saved key ending in ${savedKey.key_hint}`}>
            •••• {savedKey.key_hint}
          </span>
          <Button variant="outline" onClick={() => setReplacing(true)} disabled={remove.isPending}>
            Replace
          </Button>
          <Button variant="destructive" onClick={removeKey} disabled={remove.isPending}>
            {remove.isPending && <Loader2 className="animate-spin" aria-hidden="true" />}
            Remove
          </Button>
        </div>
      )}

      {error && (
        <p role="alert" className="text-sm text-destructive">
          {error}
        </p>
      )}
    </div>
  )
}
