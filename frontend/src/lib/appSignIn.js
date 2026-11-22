import { useEffect } from 'react'
import { toast } from 'sonner'
import { safeUrl } from '@/components/chat/cards/format'
import { useCheckApps, useConnectApp, useRefreshApp } from './queries'

/**
 * Signing in to an app for one agent, from the Apps step or from the chat. The sign-in runs in
 * another window; when it says it is done, or the user comes back to this one, each unfinished
 * sign-in is checked with the server (which asks Composio: nothing from the window is trusted).
 */
export function useAppSignIn(agentId, apps) {
  const connect = useConnectApp(agentId)
  const refresh = useRefreshApp(agentId)
  const pending = (apps ?? []).filter((app) => app.status === 'pending').map((app) => app.app).join(',')
  const refreshApp = refresh.mutate

  useEffect(() => {
    if (!pending) return undefined
    const check = () => pending.split(',').forEach((app) => refreshApp(app))
    const onMessage = (event) => {
      if (event.origin === window.location.origin && event.data?.type === 'app-connected') check()
    }
    window.addEventListener('message', onMessage)
    window.addEventListener('focus', check)
    return () => {
      window.removeEventListener('message', onMessage)
      window.removeEventListener('focus', check)
    }
  }, [pending, refreshApp])

  function startConnect(app) {
    // Opened right away, on the click itself, so the browser doesn't block it as a pop-up.
    const popup = window.open('', '_blank', 'width=620,height=760')
    connect.mutate(app.app, {
      onSuccess: ({ redirect_url }) => {
        const url = safeUrl(redirect_url)
        if (!url) {
          popup?.close()
          toast.error(`${app.name} couldn't start its sign-in. Try again.`)
        } else if (popup) popup.location.href = url
        else window.location.href = url // pop-ups are blocked: sign in in this tab instead
      },
      onError: (error) => {
        popup?.close()
        toast.error(error.message)
      },
    })
  }

  return { connect, refresh, startConnect }
}

/** Asks the server, once per page open, whether the agent's connections still work. */
export function useCheckAppsOnOpen(agentId, enabled = true) {
  const check = useCheckApps(agentId)
  const run = check.mutate
  useEffect(() => {
    if (enabled && agentId) run()
  }, [agentId, enabled, run])
}
