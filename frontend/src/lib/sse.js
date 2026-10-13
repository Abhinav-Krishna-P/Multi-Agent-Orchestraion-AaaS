import { fetchEventSource } from '@microsoft/fetch-event-source'
import { API_URL, ApiError, SESSION_EXPIRED_MESSAGE, errorFromResponse, getAccessToken, handleUnauthorized } from './api'

/**
 * Sends a chat message (or a retry) and reads the reply as it streams.
 *
 * The browser's own EventSource cannot send a POST with an Authorization header, so
 * this uses fetch-event-source. It resolves when the stream ends, and rejects with an
 * ApiError if the server refuses the request before streaming starts.
 * Returns { finished: true } only if the server sent its final `done` event.
 */
export async function streamChat({ sessionId, body, signal, onOpen, onToken, onError, onDone }) {
  const token = await getAccessToken()
  let finished = false

  await fetchEventSource(`${API_URL}/sessions/${sessionId}/chat`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${token}` },
    body: JSON.stringify(body),
    signal,
    openWhenHidden: true, // keep streaming when the tab is in the background

    async onopen(response) {
      if (response.ok) {
        onOpen?.() // the server accepted the message and has saved it
        return
      }
      if (response.status === 401) {
        await handleUnauthorized()
        throw new ApiError(401, 'unauthorized', SESSION_EXPIRED_MESSAGE)
      }
      throw await errorFromResponse(response)
    },

    onmessage(event) {
      if (!event.data) return
      const data = JSON.parse(event.data)
      if (event.event === 'token') onToken(data.text)
      else if (event.event === 'error') onError(data)
      else if (event.event === 'done') {
        finished = true
        onDone(data)
      }
    },

    // The library retries by default; rethrowing stops it, so a message is never sent twice.
    onerror(error) {
      throw error
    },
  })

  return { finished }
}
