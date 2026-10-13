import { useState } from 'react'
import { Button } from '@/components/ui/button'
import { Label } from '@/components/ui/label'
import { Skeleton } from '@/components/ui/skeleton'
import { Textarea } from '@/components/ui/textarea'
import { usePersonas, useUpdateAgent } from '@/lib/queries'
import { cn } from '@/lib/utils'
import { StepFooter } from './StepFooter'

const CUSTOM = 'custom'
const MAX_PROMPT = 20000

/** Which card is selected for a saved agent: its persona, Custom prompt, or nothing yet. */
function initialChoice(agent) {
  if (agent.persona_key) return agent.persona_key
  return agent.system_prompt ? CUSTOM : null
}

function PersonaCard({ selected, title, description, onSelect }) {
  return (
    <button
      type="button"
      role="radio"
      aria-checked={selected}
      onClick={onSelect}
      className={cn(
        'flex cursor-pointer flex-col gap-1 rounded-xl border p-3 text-left outline-none transition-colors focus-visible:ring-3 focus-visible:ring-ring/50',
        selected ? 'border-primary bg-primary/5 ring-1 ring-primary' : 'hover:bg-muted',
      )}
    >
      <span className="text-sm font-medium">{title}</span>
      <span className="text-xs text-muted-foreground">{description}</span>
    </button>
  )
}

export default function Behavior({ agent, onNext, onBack }) {
  const personas = usePersonas()
  const update = useUpdateAgent()
  const [choice, setChoice] = useState(() => initialChoice(agent))
  const [prompt, setPrompt] = useState(agent.system_prompt)
  const [error, setError] = useState(null)

  function choosePersona(persona) {
    setChoice(persona.key)
    setPrompt(persona.prompt)
    setError(null)
  }

  function chooseCustom() {
    if (choice === CUSTOM) return
    setChoice(CUSTOM)
    setPrompt(agent.custom_prompt ?? '')
    setError(null)
  }

  function onSubmit(event) {
    event.preventDefault()
    if (!choice) return setError('Choose a behavior, or pick Custom prompt and write your own.')
    if (!prompt.trim()) return setError('Write the prompt that tells your agent how to behave.')
    if (prompt.length > MAX_PROMPT) return setError('Use 20,000 characters or fewer.')
    setError(null)
    update.mutate(
      { id: agent.id, persona_key: choice === CUSTOM ? null : choice, system_prompt: prompt },
      { onSuccess: onNext },
    )
  }

  if (personas.isPending) {
    return (
      <div className="grid gap-3 sm:grid-cols-2 md:grid-cols-3" role="status" aria-label="Loading behaviors">
        {Array.from({ length: 6 }, (_, i) => (
          <Skeleton key={i} className="h-20" />
        ))}
      </div>
    )
  }
  if (personas.isError) {
    return (
      <div className="flex flex-col items-start gap-3 rounded-xl border p-6">
        <p className="text-sm text-destructive">The behaviors couldn&apos;t load.</p>
        <Button variant="outline" onClick={() => personas.refetch()}>
          Retry
        </Button>
      </div>
    )
  }

  return (
    <form onSubmit={onSubmit} className="flex flex-col gap-6" noValidate>
      <div className="flex flex-col gap-2">
        <span id="behavior-label" className="text-sm font-medium">
          How should your agent behave?
        </span>
        <div role="radiogroup" aria-labelledby="behavior-label" className="grid gap-3 sm:grid-cols-2 md:grid-cols-3">
          {personas.data.map((persona) => (
            <PersonaCard
              key={persona.key}
              selected={choice === persona.key}
              title={persona.name}
              description={persona.description}
              onSelect={() => choosePersona(persona)}
            />
          ))}
          <PersonaCard
            selected={choice === CUSTOM}
            title="Custom prompt"
            description="Write your own instructions from scratch."
            onSelect={chooseCustom}
          />
        </div>
      </div>

      <div className="flex flex-col gap-2">
        <Label htmlFor="agent-prompt">Prompt</Label>
        <Textarea
          id="agent-prompt"
          rows={10}
          value={prompt}
          onChange={(event) => setPrompt(event.target.value)}
          placeholder={choice ? 'Describe the role, tone and rules your agent should follow.' : 'Choose a behavior above to start.'}
          aria-describedby="agent-prompt-help"
          className="max-h-96"
        />
        <p id="agent-prompt-help" className="text-sm text-muted-foreground">
          This is the full instruction your agent follows. You can edit it.
        </p>
      </div>

      <StepFooter onBack={onBack} saving={update.isPending} error={error ?? update.error?.message} />
    </form>
  )
}
