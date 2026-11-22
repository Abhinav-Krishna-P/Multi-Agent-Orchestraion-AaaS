import { SlidersHorizontal } from 'lucide-react'
import { useId, useState } from 'react'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'

const today = () => new Date().toLocaleDateString('en-CA') // YYYY-MM-DD in local time
const SKIP_MESSAGE = 'Search with what you already know, without more filters.'

/** Problems the user must fix before the form can be sent, by field name. */
function validate(fields, values) {
  const errors = {}
  for (const field of fields) {
    const value = values[field.name]
    if (field.required && !String(value ?? '').trim()) errors[field.name] = `Fill in ${field.label.toLowerCase()}.`
    else if (field.type === 'email' && String(value ?? '').trim() && !/^\S+@\S+\.\S+$/.test(String(value).trim()))
      errors[field.name] = 'Enter a valid email address.'
    else if (field.type === 'number' && value !== '' && value != null && Number(value) < 0)
      errors[field.name] = 'Use a positive number.'
    else if (field.type === 'date' && value && value < today()) errors[field.name] = "This date is in the past."
  }
  // A date range: the second date must come after the first.
  const dates = fields.filter((field) => field.type === 'date')
  if (dates.length === 2) {
    const [start, end] = dates.map((field) => values[field.name])
    const pair = !dates[0].required // a stay: both dates or neither; a flight: the return is optional
    if (pair && Boolean(start) !== Boolean(end)) errors[dates[start ? 1 : 0].name] = 'Pick both dates, or neither.'
    else if (start && end && (pair ? end <= start : end < start)) {
      errors[dates[1].name] = `${dates[1].label} can't be ${pair ? 'on or ' : ''}before ${dates[0].label.toLowerCase()}.`
    }
  }
  const min = values.min_price
  const max = values.max_price
  if (min !== '' && max !== '' && min != null && max != null && Number(min) > Number(max)) {
    errors.max_price = 'The maximum must be higher than the minimum.'
  }
  return errors
}

/**
 * The chosen values as a chat message the agent can act on: by the tool's own argument names for
 * a search, and in the user's words (field labels, chosen option labels) for an automation.
 */
function toMessage(form, values) {
  const automation = form.tool === 'automation'
  const shown = (field) =>
    automation && field.type === 'select'
      ? (field.options.find((option) => String(option.value) === String(values[field.name]))?.label ?? values[field.name])
      : values[field.name]
  const parts = form.fields
    .filter((field) => values[field.name] !== '' && values[field.name] != null)
    .map((field) => `${automation ? field.label : field.name}: ${shown(field)}`)
  return automation ? `Here are the details. ${parts.join('; ')}` : `${form.title} with these details. ${parts.join('; ')}`
}

/**
 * A tool's details form, shown in the chat. The agent asked for it (kind "ask"), or it is
 * offered after a search so the user can refine it (kind "refine").
 */
export function DetailsCard({ form, disabled, onSend, onCancel }) {
  const id = useId()
  const [values, setValues] = useState(() =>
    Object.fromEntries(form.fields.map((field) => [field.name, form.values[field.name] ?? (field.type === 'select' ? field.options[0]?.value : '')])),
  )
  const [errors, setErrors] = useState({})
  const automation = form.tool === 'automation'

  const set = (name, value) => setValues((current) => ({ ...current, [name]: value }))

  function submit(event) {
    event.preventDefault()
    const found = validate(form.fields, values)
    setErrors(found)
    if (Object.keys(found).length === 0) onSend(toMessage(form, values))
  }

  return (
    <form onSubmit={submit} noValidate className="mt-3 flex flex-col gap-3 rounded-xl border bg-background p-4">
      <p className="flex items-center gap-2 text-sm font-medium">
        <SlidersHorizontal className="size-4" aria-hidden="true" /> {form.title}
      </p>
      <div className="grid gap-3 sm:grid-cols-2">
        {form.fields.map((field) => {
          const fieldId = `${id}-${field.name}`
          const error = errors[field.name]
          return (
            <div key={field.name} className={field.type === 'text' ? 'flex flex-col gap-1.5 sm:col-span-2' : 'flex flex-col gap-1.5'}>
              <Label htmlFor={fieldId}>
                {field.label}
                {!field.required && <span className="font-normal text-muted-foreground"> (optional)</span>}
              </Label>
              {field.type === 'select' ? (
                <Select value={String(values[field.name])} onValueChange={(value) => set(field.name, value)} disabled={disabled}>
                  <SelectTrigger id={fieldId} className="w-full">
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    {field.options.map((option) => (
                      <SelectItem key={option.value} value={option.value}>
                        {option.label}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              ) : (
                <Input
                  id={fieldId}
                  type={field.type}
                  min={field.type === 'date' ? today() : field.type === 'number' ? 0 : undefined}
                  value={values[field.name]}
                  onChange={(event) => set(field.name, event.target.value)}
                  disabled={disabled}
                  aria-invalid={error ? true : undefined}
                  aria-describedby={error ? `${fieldId}-error` : undefined}
                />
              )}
              {error && (
                <p id={`${fieldId}-error`} className="text-xs text-destructive">
                  {error}
                </p>
              )}
            </div>
          )
        })}
      </div>
      <div className="flex flex-wrap justify-end gap-2">
        {automation ? null : form.kind === 'ask' ? (
          <Button type="button" variant="outline" disabled={disabled} onClick={() => onSend(SKIP_MESSAGE)}>
            Skip filters
          </Button>
        ) : (
          <Button type="button" variant="outline" disabled={disabled} onClick={onCancel}>
            Cancel
          </Button>
        )}
        <Button type="submit" disabled={disabled}>
          {automation ? 'Continue' : 'Search'}
        </Button>
      </div>
    </form>
  )
}
