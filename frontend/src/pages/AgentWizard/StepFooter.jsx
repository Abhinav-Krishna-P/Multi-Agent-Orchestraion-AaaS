import { Loader2 } from 'lucide-react'
import { Button } from '@/components/ui/button'

/** Back / Continue row shared by the wizard steps, with the step's save error above it. */
export function StepFooter({ onBack, error, saving, continueLabel = 'Continue', continueDisabled, children, form }) {
  return (
    <div className="flex flex-col gap-3 border-t pt-4">
      {error && (
        <p role="alert" className="text-sm text-destructive">
          {error}
        </p>
      )}
      <div className="flex items-center gap-2">
        {onBack && (
          <Button type="button" variant="outline" onClick={onBack} disabled={saving}>
            Back
          </Button>
        )}
        <div className="flex-1" />
        {children}
        <Button type="submit" form={form} disabled={saving || continueDisabled}>
          {saving && <Loader2 className="animate-spin" aria-hidden="true" />}
          {continueLabel}
        </Button>
      </div>
    </div>
  )
}
