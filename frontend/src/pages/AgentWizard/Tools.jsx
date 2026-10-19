import { useState } from 'react'
import { Button } from '@/components/ui/button'
import { Checkbox } from '@/components/ui/checkbox'
import { Label } from '@/components/ui/label'
import { Skeleton } from '@/components/ui/skeleton'
import { useSetAgentTools, useToolCatalog } from '@/lib/queries'
import { StepFooter } from './StepFooter'

export default function Tools({ agent, onNext, onBack }) {
  const catalog = useToolCatalog()
  const setTools = useSetAgentTools()
  const [selected, setSelected] = useState(() => new Set(agent.tools))

  if (catalog.isPending) {
    return (
      <div className="flex flex-col gap-3" role="status" aria-label="Loading tools">
        <Skeleton className="h-6 w-32" />
        <Skeleton className="h-12" />
        <Skeleton className="h-12" />
      </div>
    )
  }
  if (catalog.isError) {
    return (
      <div className="flex flex-col items-start gap-3 rounded-xl border p-6">
        <p className="text-sm text-destructive">The tools couldn&apos;t load.</p>
        <Button variant="outline" onClick={() => catalog.refetch()}>
          Retry
        </Button>
      </div>
    )
  }

  function toggle(names, on) {
    setSelected((current) => {
      const next = new Set(current)
      for (const name of names) {
        if (on) next.add(name)
        else next.delete(name)
      }
      return next
    })
  }

  function onSubmit(event) {
    event.preventDefault()
    setTools.mutate({ id: agent.id, tools: [...selected] }, { onSuccess: onNext })
  }

  return (
    <form onSubmit={onSubmit} className="flex flex-col gap-6">
      <p className="text-sm text-muted-foreground">
        Choose what your agent can do besides talking. It uses a tool only when a question needs it.
      </p>

      {catalog.data.groups.map((group) => {
        const names = group.tools.map((tool) => tool.name)
        const allOn = names.every((name) => selected.has(name))
        return (
          <fieldset key={group.name} className="flex flex-col gap-3">
            <div className="flex items-center justify-between gap-3">
              <legend className="text-sm font-medium">{group.name}</legend>
              <Button type="button" variant="link" className="h-auto p-0" onClick={() => toggle(names, !allOn)}>
                {allOn ? 'Clear all' : 'Select all'}
              </Button>
            </div>
            <div className="divide-y rounded-xl border">
              {group.tools.map((tool) => (
                <div key={tool.name} className="flex items-start gap-3 p-3">
                  <Checkbox
                    id={`tool-${tool.name}`}
                    checked={selected.has(tool.name)}
                    onCheckedChange={(checked) => toggle([tool.name], checked === true)}
                    className="mt-0.5"
                  />
                  <div>
                    <Label htmlFor={`tool-${tool.name}`}>{tool.label}</Label>
                    <p className="mt-1 text-sm text-muted-foreground">{tool.description}</p>
                  </div>
                </div>
              ))}
            </div>
          </fieldset>
        )
      })}

      <StepFooter onBack={onBack} saving={setTools.isPending} error={setTools.error?.message} />
    </form>
  )
}
