import { useEffect, useRef } from 'react'
import { Button } from '@/components/ui/button'
import { Message } from './Message'

// How close to the bottom still counts as "at the bottom".
const STICK_THRESHOLD = 80

/**
 * The scrolling list of messages. It follows new text to the bottom unless the
 * user has scrolled up to read something earlier.
 */
export function MessageList({
  messages,
  streamingText,
  streamingTools,
  streamingSources,
  isStreaming,
  error,
  onRetry,
  emptyHint,
  onSendForm,
  formDisabled,
}) {
  const containerRef = useRef(null)
  const stickRef = useRef(true)

  function onScroll() {
    const el = containerRef.current
    stickRef.current = el.scrollHeight - el.scrollTop - el.clientHeight < STICK_THRESHOLD
  }

  useEffect(() => {
    const el = containerRef.current
    if (el && stickRef.current) el.scrollTop = el.scrollHeight
  }, [messages, streamingText, streamingTools, streamingSources, isStreaming, error])

  const empty = messages.length === 0 && !isStreaming

  return (
    <div ref={containerRef} onScroll={onScroll} className="min-h-0 flex-1 overflow-y-auto">
      {empty ? (
        <div className="flex h-full items-center justify-center p-6 text-center text-sm text-muted-foreground">
          {emptyHint}
        </div>
      ) : (
        <div className="mx-auto flex max-w-3xl flex-col gap-4 p-4" aria-live="polite">
          {messages.map((message, index) => (
            <Message
              key={message.id}
              role={message.role}
              content={message.content}
              tools={message.tools}
              sources={message.sources}
              form={message.form}
              formActive={index === messages.length - 1 && !isStreaming}
              formDisabled={formDisabled}
              onSendForm={onSendForm}
            />
          ))}
          {isStreaming && (
            <Message
              role="assistant"
              content={streamingText}
              tools={streamingTools}
              sources={streamingSources}
              streaming
            />
          )}
          {error && (
            <div role="alert" className="flex flex-wrap items-center gap-3 rounded-xl border border-destructive/30 bg-destructive/5 px-4 py-3 text-sm">
              <span className="flex-1 text-destructive">{error.message}</span>
              {onRetry && (
                <Button variant="outline" size="sm" onClick={onRetry}>
                  Retry
                </Button>
              )}
            </div>
          )}
        </div>
      )}
    </div>
  )
}
