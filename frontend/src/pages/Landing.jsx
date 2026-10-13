import { BarChart3, Bot, Loader2, MessageSquare } from 'lucide-react'
import { useState } from 'react'
import { Navigate } from 'react-router-dom'
import { Button } from '@/components/ui/button'
import { takeAuthMessage } from '@/lib/api'
import { useAuth } from '@/lib/auth'

const SIGN_IN_FAILED = "Google sign-in didn't finish. Try again."

/** Supabase reports a failed or cancelled sign-in in the URL it sends the user back to. */
function signInFailedOnReturn() {
  const url = new URL(window.location.href)
  const failed = url.searchParams.has('error') || url.hash.includes('error=')
  if (failed) window.history.replaceState(null, '', url.pathname)
  return failed
}

function GoogleIcon() {
  return (
    <svg viewBox="0 0 24 24" className="size-4" aria-hidden="true">
      <path fill="#4285F4" d="M22.56 12.25c0-.78-.07-1.53-.2-2.25H12v4.26h5.92a5.06 5.06 0 0 1-2.2 3.32v2.77h3.57c2.08-1.92 3.27-4.74 3.27-8.1z" />
      <path fill="#34A853" d="M12 23c2.97 0 5.46-.98 7.28-2.66l-3.57-2.77c-.98.66-2.23 1.06-3.71 1.06-2.86 0-5.29-1.93-6.16-4.53H2.18v2.84A11 11 0 0 0 12 23z" />
      <path fill="#FBBC05" d="M5.84 14.1a6.6 6.6 0 0 1 0-4.2V7.06H2.18a11 11 0 0 0 0 9.88l3.66-2.84z" />
      <path fill="#EA4335" d="M12 5.38c1.62 0 3.06.56 4.21 1.64l3.15-3.15C17.45 2.09 14.97 1 12 1A11 11 0 0 0 2.18 7.06l3.66 2.84C6.71 7.3 9.14 5.38 12 5.38z" />
    </svg>
  )
}

export default function Landing() {
  const { session, loading, signInWithGoogle } = useAuth()
  const [redirecting, setRedirecting] = useState(false)
  const [message, setMessage] = useState(() => takeAuthMessage() ?? (signInFailedOnReturn() ? SIGN_IN_FAILED : null))

  if (session) return <Navigate to="/app/agents" replace />

  async function signIn() {
    setMessage(null)
    setRedirecting(true)
    try {
      await signInWithGoogle()
    } catch {
      setRedirecting(false)
      setMessage(SIGN_IN_FAILED)
    }
  }

  return (
    <div className="flex min-h-svh flex-col px-6 py-6 sm:px-12">
      <header className="flex items-center gap-2 font-semibold">
        <Bot className="size-5 text-primary" aria-hidden="true" />
        Custom Agent Platform
      </header>

      <main className="flex flex-1 flex-col justify-center">
        <div className="max-w-xl">
          <h1 className="text-4xl font-semibold tracking-tight sm:text-5xl">Build your own AI agent</h1>
          <p className="mt-4 text-lg text-muted-foreground">
            Give it a personality, your documents, tools and app connections. Chat with it using your own Gemini or
            OpenAI key.
          </p>

          <Button size="lg" className="mt-8 h-11 px-5 text-base" onClick={signIn} disabled={redirecting || loading}>
            {redirecting ? <Loader2 className="size-4 animate-spin" aria-hidden="true" /> : <GoogleIcon />}
            Continue with Google
          </Button>
          {message && (
            <p role="alert" className="mt-3 text-sm text-destructive">
              {message}
            </p>
          )}

          <ul className="mt-10 flex flex-col gap-3 text-sm text-muted-foreground sm:flex-row sm:gap-6">
            <li className="flex items-center gap-2">
              <Bot className="size-4" aria-hidden="true" /> Create an agent
            </li>
            <li className="flex items-center gap-2">
              <MessageSquare className="size-4" aria-hidden="true" /> Chat with it
            </li>
            <li className="flex items-center gap-2">
              <BarChart3 className="size-4" aria-hidden="true" /> See how it performs
            </li>
          </ul>
        </div>
      </main>
    </div>
  )
}
