import { zodResolver } from '@hookform/resolvers/zod'
import { useForm } from 'react-hook-form'
import { z } from 'zod'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Textarea } from '@/components/ui/textarea'
import { useCreateAgent, useUpdateAgent } from '@/lib/queries'
import { StepFooter } from './StepFooter'

const schema = z.object({
  name: z.string().trim().min(1, 'Give your agent a name.').max(100, 'Use 100 characters or fewer.'),
  description: z.string().trim().max(500, 'Use 500 characters or fewer.'),
})

export default function Basics({ agent, onCreated, onNext }) {
  const create = useCreateAgent()
  const update = useUpdateAgent()
  const saving = create.isPending || update.isPending
  const saveError = create.error ?? update.error

  const {
    register,
    handleSubmit,
    formState: { errors },
  } = useForm({
    resolver: zodResolver(schema),
    defaultValues: { name: agent?.name ?? '', description: agent?.description ?? '' },
  })

  function onSubmit(values) {
    if (agent) update.mutate({ id: agent.id, ...values }, { onSuccess: onNext })
    else create.mutate(values, { onSuccess: onCreated })
  }

  return (
    <form onSubmit={handleSubmit(onSubmit)} className="flex flex-col gap-6" noValidate>
      <div className="flex flex-col gap-2">
        <Label htmlFor="agent-name">Name</Label>
        <Input
          id="agent-name"
          placeholder="Support Bot"
          autoFocus
          aria-invalid={errors.name ? true : undefined}
          aria-describedby={errors.name ? 'agent-name-error' : undefined}
          {...register('name')}
        />
        {errors.name && (
          <p id="agent-name-error" className="text-sm text-destructive">
            {errors.name.message}
          </p>
        )}
      </div>

      <div className="flex flex-col gap-2">
        <Label htmlFor="agent-description">
          Description <span className="font-normal text-muted-foreground">(optional)</span>
        </Label>
        <Textarea
          id="agent-description"
          rows={3}
          placeholder="Answers customer questions about our store"
          aria-invalid={errors.description ? true : undefined}
          aria-describedby={errors.description ? 'agent-description-error' : undefined}
          {...register('description')}
        />
        {errors.description && (
          <p id="agent-description-error" className="text-sm text-destructive">
            {errors.description.message}
          </p>
        )}
      </div>

      <StepFooter saving={saving} error={saveError?.message} />
    </form>
  )
}
