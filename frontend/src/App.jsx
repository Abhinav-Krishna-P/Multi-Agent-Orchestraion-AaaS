import { QueryClientProvider } from '@tanstack/react-query'
import { Loader2 } from 'lucide-react'
import { BrowserRouter, Navigate, Outlet, Route, Routes } from 'react-router-dom'
import { Toaster } from '@/components/ui/sonner'
import AppShell from '@/layouts/AppShell'
import { AuthProvider, useAuth } from '@/lib/auth'
import { queryClient } from '@/lib/queryClient'
import AgentsList from '@/pages/AgentsList'
import AgentWizard from '@/pages/AgentWizard'
import Analytics from '@/pages/Analytics'
import Automations from '@/pages/Automations'
import Chat from '@/pages/Chat'
import Connected from '@/pages/Connected'
import Landing from '@/pages/Landing'

function FullPageSpinner() {
  return (
    <div className="flex h-svh items-center justify-center" role="status" aria-label="Loading">
      <Loader2 className="size-6 animate-spin text-muted-foreground" aria-hidden="true" />
    </div>
  )
}

/** Everything under /app needs a signed-in user; anyone else goes back to the landing page. */
function RequireAuth() {
  const { session, loading } = useAuth()
  if (loading) return <FullPageSpinner />
  if (!session) return <Navigate to="/" replace />
  return <Outlet />
}

function LandingRoute() {
  const { loading } = useAuth()
  return loading ? <FullPageSpinner /> : <Landing />
}

export default function App() {
  return (
    <QueryClientProvider client={queryClient}>
      <AuthProvider>
        <BrowserRouter>
          <Routes>
            <Route path="/" element={<LandingRoute />} />
            <Route element={<RequireAuth />}>
              <Route path="/app/connected" element={<Connected />} />
              <Route path="/app" element={<AppShell />}>
                <Route index element={<Navigate to="/app/agents" replace />} />
                <Route path="agents" element={<AgentsList />} />
                <Route path="agents/new" element={<AgentWizard />} />
                <Route path="agents/:agentId" element={<AgentWizard />} />
                <Route path="chat" element={<Chat />} />
                <Route path="chat/:agentId/:sessionId?" element={<Chat />} />
                <Route path="automations/:agentId?" element={<Automations />} />
                <Route path="analytics/:agentId?" element={<Analytics />} />
              </Route>
            </Route>
            <Route path="*" element={<Navigate to="/" replace />} />
          </Routes>
        </BrowserRouter>
        <Toaster position="top-right" richColors />
      </AuthProvider>
    </QueryClientProvider>
  )
}
