import { Badge } from '@/components/ui/badge'
import { cn } from '@/lib/utils'

// Colour is never the only signal: every status also has its word.
const STATUSES = {
  live: { label: 'Live', className: 'border-green-500/30 bg-green-500/10 text-green-300' },
  draft: { label: 'Draft', className: 'border-amber-500/30 bg-amber-500/10 text-amber-300' },
  stopped: { label: 'Stopped', className: 'border-border bg-muted text-muted-foreground' },
  // Documents in a knowledge base
  pending: { label: 'Pending', className: 'border-amber-500/30 bg-amber-500/10 text-amber-300' },
  processing: { label: 'Processing', className: 'border-amber-500/30 bg-amber-500/10 text-amber-300' },
  ready: { label: 'Ready', className: 'border-green-500/30 bg-green-500/10 text-green-300' },
  failed: { label: 'Failed', className: 'border-red-500/30 bg-red-500/10 text-red-300' },
}

export function StatusBadge({ status, className }) {
  const { label, className: colors } = STATUSES[status] ?? { label: status, className: '' }
  return (
    <Badge variant="outline" className={cn(colors, className)}>
      {label}
    </Badge>
  )
}
