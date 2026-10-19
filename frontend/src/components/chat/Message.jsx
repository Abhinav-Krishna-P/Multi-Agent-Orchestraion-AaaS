import { memo } from 'react'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import { Sources } from './Sources'
import { ToolActivity } from './ToolActivity'

const REMARK_PLUGINS = [remarkGfm]
const MARKDOWN_COMPONENTS = {
  // Links in a reply go to other sites: open them in a new tab.
  a: ({ node: _node, ...props }) => <a {...props} target="_blank" rel="noreferrer noopener" />,
}

/**
 * One chat message. The user's text is shown as typed; the agent's is rendered as Markdown,
 * with the tools it used above the text and the documents it drew on below.
 */
export const Message = memo(function Message({ role, content, tools, sources, streaming = false }) {
  if (role === 'user') {
    return (
      <div className="flex justify-end">
        <div className="max-w-[85%] rounded-2xl bg-primary px-4 py-2.5 text-sm whitespace-pre-wrap text-primary-foreground [overflow-wrap:anywhere]">
          {content}
        </div>
      </div>
    )
  }
  return (
    <div className="flex justify-start">
      <div className="max-w-[85%] min-w-0 rounded-2xl bg-muted/60 px-4 py-2.5 text-sm [overflow-wrap:anywhere]">
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
        <Sources sources={sources} />
      </div>
    </div>
  )
})
