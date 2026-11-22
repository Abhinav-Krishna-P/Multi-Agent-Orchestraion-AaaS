import { ArrowUp, Square } from 'lucide-react'
import { useEffect, useRef } from 'react'
import { Button } from '@/components/ui/button'
import { Textarea } from '@/components/ui/textarea'

const MAX_LENGTH = 20000

/** The message box. Enter sends, Shift+Enter adds a line. While a reply streams, Send becomes Stop. */
export function Composer({ id, agentName, value, onChange, onSend, onStop, isStreaming, disabled, autoFocus = true }) {
  const textareaRef = useRef(null)
  const canSend = value.trim().length > 0 && value.length <= MAX_LENGTH && !isStreaming && !disabled

  const wasStreaming = useRef(false)

  useEffect(() => {
    // autoFocus={false} skips only the focus on mount; the box is still refocused when a reply ends.
    const replyEnded = wasStreaming.current && !isStreaming
    wasStreaming.current = isStreaming
    // preventScroll: on the Automations page the box sits below the list; focusing must not scroll past it.
    if (!isStreaming && (autoFocus || replyEnded)) textareaRef.current?.focus({ preventScroll: true })
  }, [isStreaming, autoFocus])

  function submit(event) {
    event.preventDefault()
    if (canSend) onSend(value.trim())
  }

  function onKeyDown(event) {
    // isComposing: Enter is confirming an IME suggestion, not sending.
    if (event.key === 'Enter' && !event.shiftKey && !event.nativeEvent.isComposing) submit(event)
  }

  return (
    <form onSubmit={submit} className="flex w-full items-end gap-2 p-4">
      <Textarea
        ref={textareaRef}
        id={id}
        rows={1}
        value={value}
        onChange={(event) => onChange(event.target.value)}
        onKeyDown={onKeyDown}
        placeholder={`Message ${agentName}…`}
        aria-label={`Message ${agentName}`}
        disabled={disabled}
        className="max-h-48 min-h-10 resize-none"
      />
      {isStreaming ? (
        <Button type="button" variant="outline" onClick={onStop} className="h-10">
          <Square aria-hidden="true" /> Stop
        </Button>
      ) : (
        <Button type="submit" disabled={!canSend} className="h-10">
          <ArrowUp aria-hidden="true" /> Send
        </Button>
      )}
    </form>
  )
}
