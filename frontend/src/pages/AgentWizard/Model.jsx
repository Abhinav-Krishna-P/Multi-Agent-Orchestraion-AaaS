import { useState } from 'react'
import { ApiKeyField } from '@/components/ApiKeyField'
import { Button } from '@/components/ui/button'
import { Label } from '@/components/ui/label'
import { RadioGroup, RadioGroupItem } from '@/components/ui/radio-group'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { Skeleton } from '@/components/ui/skeleton'
import { useLlmKeys, useModelCatalog, useUpdateAgent } from '@/lib/queries'
import { StepFooter } from './StepFooter'

const FORM_ID = 'model-step'

export default function Model({ agent, onNext, onBack, goTo }) {
  const catalog = useModelCatalog()
  const llmKeys = useLlmKeys()
  const update = useUpdateAgent()
  const [provider, setProvider] = useState(agent.llm_provider ?? '')
  const [model, setModel] = useState(agent.llm_model ?? '')

  if (catalog.isPending || llmKeys.isPending) {
    return (
      <div className="flex flex-col gap-4" role="status" aria-label="Loading models">
        <Skeleton className="h-16" />
        <Skeleton className="h-10" />
      </div>
    )
  }
  if (catalog.isError || llmKeys.isError) {
    return (
      <div className="flex flex-col items-start gap-3 rounded-xl border p-6">
        <p className="text-sm text-destructive">The models couldn&apos;t load.</p>
        <Button
          variant="outline"
          onClick={() => {
            catalog.refetch()
            llmKeys.refetch()
          }}
        >
          Retry
        </Button>
      </div>
    )
  }

  const providers = catalog.data.providers
  // With a single provider on offer there is nothing to choose: use it.
  const providerKey = provider || (providers.length === 1 ? providers[0].key : '')
  const selectedProvider = providers.find((p) => p.key === providerKey)
  const modelId = model || selectedProvider?.models[0].id || ''
  const savedKey = llmKeys.data.find((saved) => saved.provider === providerKey)

  function chooseProvider(key) {
    setProvider(key)
    // Each provider has its own models; start from its first one.
    setModel(providers.find((p) => p.key === key).models[0].id)
  }

  function onSubmit(event) {
    event.preventDefault()
    update.mutate({ id: agent.id, llm_provider: providerKey, llm_model: modelId }, { onSuccess: onNext })
  }

  return (
    <div className="flex flex-col gap-6">
      <form id={FORM_ID} onSubmit={onSubmit} className="flex flex-col gap-6">
        <div className="flex flex-col gap-2">
          <Label id="provider-label">Provider</Label>
          <RadioGroup value={providerKey} onValueChange={chooseProvider} aria-labelledby="provider-label" className="flex gap-6">
            {providers.map((p) => (
              <div key={p.key} className="flex items-center gap-2">
                <RadioGroupItem value={p.key} id={`provider-${p.key}`} />
                <Label htmlFor={`provider-${p.key}`} className="font-normal">
                  {p.name}
                </Label>
              </div>
            ))}
          </RadioGroup>
        </div>

        {selectedProvider && (
          <div className="flex flex-col gap-2">
            <Label htmlFor="agent-model">Model</Label>
            <Select value={modelId} onValueChange={setModel}>
              <SelectTrigger id="agent-model" className="w-full sm:w-96">
                <SelectValue placeholder="Choose a model" />
              </SelectTrigger>
              <SelectContent>
                {selectedProvider.models.map((m) => (
                  <SelectItem key={m.id} value={m.id}>
                    {m.name}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>
        )}
      </form>

      {/* Outside the form above: the key field has its own form and Save button. */}
      {selectedProvider && (
        <div className="flex flex-col gap-2">
          <span className="text-sm font-medium">API key</span>
          {savedKey ? (
            <p className="text-sm text-muted-foreground">
              Using your saved {selectedProvider.name} key (•••• {savedKey.key_hint}).
            </p>
          ) : (
            <>
              <ApiKeyField
                key={providerKey}
                provider={providerKey}
                providerName={selectedProvider.name}
                savedKey={undefined}
                showLabel={false}
              />
              <p className="text-sm text-muted-foreground">
                Your key is used only for your agents&apos; chat replies. It&apos;s stored encrypted.
              </p>
            </>
          )}
        </div>
      )}

      <StepFooter
        form={FORM_ID}
        onBack={onBack}
        saving={update.isPending}
        error={update.error?.message}
        continueDisabled={!providerKey || !modelId}
      >
        <Button type="button" variant="link" onClick={() => goTo('knowledge')} disabled={update.isPending}>
          Skip for now
        </Button>
      </StepFooter>
    </div>
  )
}
