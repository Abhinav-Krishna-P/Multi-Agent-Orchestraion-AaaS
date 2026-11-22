import { useQueryClient } from '@tanstack/react-query'
import { useRef, useState } from 'react'
import { keys } from '@/lib/queries'
import { streamChat } from '@/lib/sse'

export const INTERRUPTED = { message: 'The reply was interrupted. Try again.' }
// After Stop, the server saves the text written so far; give it a moment before reloading.
const STOP_SAVE_DELAY_MS = 500

const wait = (ms) => new Promise((resolve) => setTimeout(resolve, ms))

/** The user's choice on an approval card, as it shows (and is saved) in the chat. */
export function decisionText(approval, decision) {
  const verb = decision === 'approve' ? 'Approved' : 'Declined'
  if (approval.kind === 'automation') return `${verb}: ${approval.name} (automation)`
  return `${verb}: ${approval.action_name} (${approval.app_name})`
}

/**
 * One streaming chat turn against a session: the live reply state plus runTurn/stop.
 * `extraBody` is merged into every request body; `onFailure(failure, body)` runs after the
 * turn has settled and the saved messages are reloaded.
 */
export function useChatTurn({ agentId, sessionId, extraBody = {}, onFailure }) {
  const client = useQueryClient()
  const [pendingUserText, setPendingUserText] = useState(null)
  const [streamingText, setStreamingText] = useState('')
  const [streamingTools, setStreamingTools] = useState([]) // [{ id, label, ok }], ok is null while running
  const [streamingSources, setStreamingSources] = useState([])
  const [isStreaming, setIsStreaming] = useState(false)
  const [error, setError] = useState(null) // { message }
  const abortRef = useRef(null)
  const openedRef = useRef(false)

  // `shownText` is what appears as the user's message while the reply streams.
  async function runTurn(body, shownText = body.message) {
    const controller = new AbortController()
    abortRef.current = controller
    openedRef.current = false
    setError(null)
    setStreamingText('')
    setStreamingTools([])
    setStreamingSources([])
    setPendingUserText(shownText ?? null)
    setIsStreaming(true)

    let failure = null
    try {
      const { finished } = await streamChat({
        sessionId,
        body: { ...extraBody, ...body },
        signal: controller.signal,
        onOpen: () => {
          openedRef.current = true
        },
        onToken: (text) => setStreamingText((previous) => previous + text),
        onToolStart: (tool) => setStreamingTools((tools) => [...tools, { ...tool, ok: null }]),
        onToolEnd: ({ id, ok, card }) =>
          setStreamingTools((tools) => tools.map((tool) => (tool.id === id ? { ...tool, ok, card } : tool))),
        onSources: setStreamingSources,
        onError: (data) => {
          failure = data
        },
        onDone: () => {},
      })
      if (!finished && !controller.signal.aborted && !failure) failure = INTERRUPTED
    } catch (err) {
      if (!controller.signal.aborted) failure = err
    }

    if (controller.signal.aborted) await wait(STOP_SAVE_DELAY_MS)
    await Promise.all([
      client.invalidateQueries({ queryKey: keys.messages(sessionId) }),
      client.invalidateQueries({ queryKey: keys.sessions(agentId) }),
      // A connection that broke during the reply shows its Reconnect bar straight away.
      client.invalidateQueries({ queryKey: keys.integrations(agentId) }),
    ])
    setIsStreaming(false)
    setStreamingText('')
    setStreamingTools([])
    setStreamingSources([])
    setPendingUserText(null)
    if (failure) onFailure?.(failure, body)
  }

  // Ignored until the server has the message, so a double click on the shared Send/Stop
  // button can't cancel a message before it is saved.
  const stop = () => openedRef.current && abortRef.current?.abort()

  return {
    runTurn,
    stop,
    isStreaming,
    pendingUserText,
    streamingText,
    streamingTools,
    streamingSources,
    error,
    setError,
  }
}
