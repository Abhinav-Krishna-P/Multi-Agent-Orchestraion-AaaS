import { SlidersHorizontal } from 'lucide-react'
import { memo, useState } from 'react'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import { Button } from '@/components/ui/button'
import { cn } from '@/lib/utils'
import { ResultCards } from './cards'
import { DetailsCard } from './DetailsCard'
import { Sources } from './Sources'
import { ToolActivity } from './ToolActivity'

const REMARK_PLUGINS = [remarkGfm]
const MARKDOWN_COMPONENTS = {
  // Links in a reply go to other sites: open them in a new tab. A link wrapped around an
  // image shows the image's description as its text: images render as links below, and a
  // link inside a link is not valid HTML.
  a: ({ node, children, ...props }) => {
    const image = node?.children?.find((child) => child.tagName === 'img')
    return (
      <a {...props} target="_blank" rel="noreferrer noopener">
        {image ? image.properties?.alt || 'Image' : children}
      </a>
    )
  },
  // Images are never loaded: an address written into a reply (for example by text hidden in
  // a document) could carry chat content out to another site. They are shown as links.
  img: ({ node: _node, src, alt }) => (
    <a href={src} target="_blank" rel="noreferrer noopener">
      {alt || 'Image'}
    </a>
  ),
}

/**
 * One chat message. The user's text is shown as typed; the agent's is rendered as Markdown,
 * with the tools it used above the text and the documents it drew on below.
 */
/** The form that came with a reply: open when the agent asked for it, behind a button when it is a refine offer. */
function DetailsForm({ form, disabled, onSend }) {
  const [open, setOpen] = useState(form.kind === 'ask')
  if (!open) {
    return (
      <Button variant="outline" size="sm" className="mt-3" disabled={disabled} onClick={() => setOpen(true)}>
        <SlidersHorizontal aria-hidden="true" /> Refine with filters
      </Button>
    )
  }
  return <DetailsCard form={form} disabled={disabled} onSend={onSend} onCancel={() => setOpen(false)} />
}

export const Message = memo(function Message({
  role,
  content,
  tools,
  sources,
  form,
  formActive = false,
  formDisabled = false,
  onSendForm,
  streaming = false,
}) {
  if (role === 'user') {
    return (
      <div className="flex justify-end">
        <div className="max-w-[min(85%,48rem)] rounded-2xl bg-primary px-4 py-2.5 text-sm whitespace-pre-wrap text-primary-foreground [overflow-wrap:anywhere]">
          {content}
        </div>
      </div>
    )
  }
  return (
    <div className="flex justify-start">
      <div
        className={cn(
          'min-w-0 rounded-2xl bg-muted/60 px-4 py-2.5 text-sm [overflow-wrap:anywhere]',
          // A reply with result cards gets room for a row of them.
          tools?.some((tool) => tool.card) ? 'w-full max-w-[min(100%,60rem)]' : 'max-w-[min(85%,48rem)]',
        )}
      >
        <ToolActivity tools={tools} />
        {content ? (
          <div className="markdown">
            <ReactMarkdown remarkPlugins={REMARK_PLUGINS} components={MARKDOWN_COMPONENTS}>
              {content}
            </ReactMarkdown>
          </div>
        ) : (
          streaming && (
            <span className="flex items-center gap-1 py-1.5" role="status" aria-label="The agent is replying">
              <span className="size-1.5 animate-pulse rounded-full bg-muted-foreground" />
              <span className="size-1.5 animate-pulse rounded-full bg-muted-foreground [animation-delay:150ms]" />
              <span className="size-1.5 animate-pulse rounded-full bg-muted-foreground [animation-delay:300ms]" />
            </span>
          )
        )}
        <ResultCards tools={tools} />
        <Sources sources={sources} />
        {/* Only the newest reply's form can be used; an older request for details is just noted. */}
        {form && formActive && <DetailsForm form={form} disabled={formDisabled} onSend={onSendForm} />}
        {form && !formActive && form.kind === 'ask' && (
          <p className="mt-2 text-xs text-muted-foreground">Asked for details: {form.title}</p>
        )}
      </div>
    </div>
  )
})
