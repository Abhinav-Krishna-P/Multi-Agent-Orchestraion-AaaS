import { CircleCheck } from 'lucide-react'
import { useEffect } from 'react'

/**
 * Where an app's sign-in sends the user back to. It only tells the window that opened it
 * that the sign-in is over; whether it worked is always checked with the server, never taken
 * from this page's address.
 */
export default function Connected() {
  useEffect(() => {
    window.opener?.postMessage({ type: 'app-connected' }, window.location.origin)
    window.close() // works when this page was opened as a pop-up; otherwise the text below stays
  }, [])

  return (
    <main className="flex min-h-svh flex-col items-center justify-center gap-3 p-6 text-center">
      <CircleCheck className="size-10 text-green-700" aria-hidden="true" />
      <h1 className="text-xl font-semibold">Sign-in finished</h1>
      <p className="text-sm text-muted-foreground">You can close this window and go back to your agent.</p>
    </main>
  )
}
