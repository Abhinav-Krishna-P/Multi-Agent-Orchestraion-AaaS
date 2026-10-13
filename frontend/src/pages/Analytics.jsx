import { BarChart3 } from 'lucide-react'

export default function Analytics() {
  return (
    <div className="flex h-full flex-col items-center justify-center gap-3 p-8 text-center">
      <BarChart3 className="size-8 text-muted-foreground" aria-hidden="true" />
      <h1 className="text-xl font-semibold">Analytics</h1>
      <p className="max-w-sm text-sm text-muted-foreground">Analytics arrives in a later stage.</p>
    </div>
  )
}
