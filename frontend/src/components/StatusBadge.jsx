import { Badge } from '@/components/ui/badge'
import { cn } from '@/lib/utils'

// Colour is never the only signal: every status also has its word.
const STATUSES = {
  live: { label: 'Live', className: 'border-green-200 bg-green-50 text-green-800' },
  draft: { label: 'Draft', className: 'border-amber-200 bg-amber-50 text-amber-800' },
  stopped: { label: 'Stopped', className: 'border-neutral-200 bg-neutral-100 text-neutral-700' },
}

export function StatusBadge({ status, className }) {
  const { label, className: colors } = STATUSES[status] ?? { label: status, className: '' }
  return (
    <Badge variant="outline" className={cn(colors, className)}>
      {label}
    </Badge>
  )
}
