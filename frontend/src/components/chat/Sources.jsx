import { FileText } from 'lucide-react'
import { Popover, PopoverContent, PopoverTrigger } from '@/components/ui/popover'

/** The documents an answer came from. Each chip opens the passage that was used. */
export function Sources({ sources }) {
  if (!sources?.length) return null
  return (
    <div className="mt-3 flex flex-wrap items-center gap-1.5 border-t pt-2">
      <span className="text-xs text-muted-foreground">Sources</span>
      {sources.map((source, index) => (
        <Popover key={index}>
          <PopoverTrigger className="flex max-w-56 cursor-pointer items-center gap-1 rounded-full border bg-background px-2 py-0.5 text-xs outline-none hover:bg-muted focus-visible:ring-3 focus-visible:ring-ring/50">
            <FileText className="size-3 shrink-0" aria-hidden="true" />
            <span className="truncate">{source.document_name}</span>
            {source.page != null && <span className="shrink-0 text-muted-foreground">p. {source.page}</span>}
          </PopoverTrigger>
          <PopoverContent className="w-80 text-sm" align="start">
            <p className="mb-1 font-medium [overflow-wrap:anywhere]">
              {source.document_name}
              {source.page != null && `, page ${source.page}`}
            </p>
            <p className="whitespace-pre-wrap text-muted-foreground [overflow-wrap:anywhere]">{source.excerpt}</p>
          </PopoverContent>
        </Popover>
      ))}
    </div>
  )
}
