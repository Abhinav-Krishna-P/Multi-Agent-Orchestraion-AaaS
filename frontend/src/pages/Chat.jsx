import { useQueryClient } from '@tanstack/react-query'
import { Loader2, MessagesSquare, Plus } from 'lucide-react'
import { useEffect, useRef, useState } from 'react'
import { Link, useLocation, useNavigate, useOutletContext, useParams } from 'react-router-dom'
import { toast } from 'sonner'
import { AgentSelect } from '@/components/AgentSelect'
import { StatusBadge } from '@/components/StatusBadge'
import { Composer } from '@/components/chat/Composer'
import { MessageList } from '@/components/chat/MessageList'
import { SessionList } from '@/components/chat/SessionList'
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from '@/components/ui/alert-dialog'
import { Button } from '@/components/ui/button'
import { Sheet, SheetContent, SheetDescription, SheetHeader, SheetTitle } from '@/components/ui/sheet'
import { Skeleton } from '@/components/ui/skeleton'
import {
  keys,
  useAgents,
  useCreateSession,
  useDeleteSession,
  useDeployAgent,
  useLlmKeys,
  useMessages,
  useModelCatalog,
  useSessions,
} from '@/lib/queries'
import { streamChat } from '@/lib/sse'

const INTERRUPTED = { message: 'The reply was interrupted. Try again.' }
// After Stop, the server saves the text written so far; give it a moment before reloading.
const STOP_SAVE_DELAY_MS = 500
// Refusals that mean the page's view of the agent or keys is out of date.
const STALE_STATE_CODES = ['missing_api_key', 'agent_not_live', 'llm_not_configured']

const wait = (ms) => new Promise((resolve) => setTimeout(resolve, ms))

function CenteredNote({ children }) {
  return <div className="flex h-full flex-col items-center justify-center gap-4 p-8 text-center">{children}</div>
}

/** Shown in place of the message box when the user must do something before chatting. */
function BlockedBar({ children, action }) {
  return (
    <div className="mx-auto flex w-full max-w-3xl flex-wrap items-center gap-3 p-4">
      <p className="flex-1 text-sm text-muted-foreground">{children}</p>
      {action}
    </div>
  )
}

function ChatThread({ agent, sessionId, providerName, modelName }) {
  const client = useQueryClient()
  const navigate = useNavigate()
  const location = useLocation()
  const { openApiKeys } = useOutletContext()
  const llmKeys = useLlmKeys()
  const messages = useMessages(sessionId)
  const createSession = useCreateSession(agent.id)
  const deploy = useDeployAgent()

  const [draft, setDraft] = useState('')
  const [pendingUserText, setPendingUserText] = useState(null)
  const [streamingText, setStreamingText] = useState('')
  const [isStreaming, setIsStreaming] = useState(false)
  const [error, setError] = useState(null) // { message }
  const abortRef = useRef(null)
  const openedRef = useRef(false)
  const sentFirstRef = useRef(false)

  async function runTurn(targetSessionId, body) {
    const controller = new AbortController()
    abortRef.current = controller
    openedRef.current = false
    setError(null)
    setStreamingText('')
    setPendingUserText(body.message ?? null)
    setIsStreaming(true)

    let failure = null
    try {
      const { finished } = await streamChat({
        sessionId: targetSessionId,
        body,
        signal: controller.signal,
        onOpen: () => {
          openedRef.current = true
        },
        onToken: (text) => setStreamingText((previous) => previous + text),
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
      client.invalidateQueries({ queryKey: keys.messages(targetSessionId) }),
      client.invalidateQueries({ queryKey: keys.sessions(agent.id) }),
    ])
    setIsStreaming(false)
    setStreamingText('')
    setPendingUserText(null)
    if (failure) reportFailure(failure, targetSessionId, body)
  }

  function reportFailure(failure, targetSessionId, body) {
    if (failure.status === 401) return // signed out; the app is already leaving this page
    const saved = client.getQueryData(keys.messages(targetSessionId)) ?? []
    const unanswered = saved[saved.length - 1]?.role === 'user'
    const refused = failure.status >= 400 // the server said no before saving anything
    // Give the text back whenever it was not saved, instead of losing it.
    if (body.message && (refused || !unanswered)) setDraft(body.message)

    if (STALE_STATE_CODES.includes(failure.code)) {
      client.invalidateQueries({ queryKey: keys.llmKeys })
      client.invalidateQueries({ queryKey: keys.agents })
      return
    }
    if (failure.code === 'reply_in_progress') {
      toast.error(failure.message)
      return
    }
    // Only the server's own errors carry a code; anything else is a dropped connection.
    setError({ message: failure.code ? failure.message : INTERRUPTED.message })
  }

  async function send(text) {
    setDraft('')
    if (sessionId) return runTurn(sessionId, { message: text })
    // First message of a new chat: create the chat, open it, and send from there.
    try {
      const session = await createSession.mutateAsync()
      navigate(`/app/chat/${agent.id}/${session.id}`, { state: { firstMessage: text } })
    } catch (err) {
      setDraft(text)
      if (STALE_STATE_CODES.includes(err.code)) client.invalidateQueries({ queryKey: keys.agents })
      else setError({ message: err.message })
    }
  }

  // A chat opened by send() above carries its first message in the navigation state.
  useEffect(() => {
    const first = location.state?.firstMessage
    if (!sessionId || !first || sentFirstRef.current) return
    sentFirstRef.current = true
    // Clear the state first, so reloading the page never sends the message again.
    navigate(location.pathname, { replace: true, state: null })
    runTurn(sessionId, { message: first })
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [sessionId])

  function startAgent() {
    deploy.mutate(agent.id, {
      onSuccess: () => toast.success(`${agent.name} is live`),
      onError: (err) => toast.error(err.message),
    })
  }

  if (sessionId && messages.isError) {
    const gone = messages.error?.status === 404
    return (
      <CenteredNote>
        <p className="text-sm text-destructive">{gone ? "This chat doesn't exist any more." : "This chat couldn't load."}</p>
        {gone ? (
          <Button variant="outline" asChild>
            <Link to={`/app/chat/${agent.id}`}>Start a new chat</Link>
          </Button>
        ) : (
          <Button variant="outline" onClick={() => messages.refetch()}>
            Retry
          </Button>
        )}
      </CenteredNote>
    )
  }

  const savedMessages = sessionId ? (messages.data ?? []) : []
  const shownMessages = pendingUserText
    ? [...savedMessages, { id: 'pending', role: 'user', content: pendingUserText }]
    : savedMessages
  const unanswered = !isStreaming && savedMessages[savedMessages.length - 1]?.role === 'user'
  const shownError = error ?? (unanswered ? { message: "This message didn't get a reply." } : null)
  const hasKey = llmKeys.data?.some((saved) => saved.provider === agent.llm_provider)
  const starting = createSession.isPending

  let footer
  if (agent.status === 'stopped') {
    footer = (
      <BlockedBar
        action={
          <Button onClick={startAgent} disabled={deploy.isPending}>
            {deploy.isPending && <Loader2 className="animate-spin" aria-hidden="true" />}
            Start agent
          </Button>
        }
      >
        This agent is stopped. Start it to chat.
      </BlockedBar>
    )
  } else if (!agent.llm_provider) {
    footer = (
      <BlockedBar
        action={
          <Button asChild>
            <Link to={`/app/agents/${agent.id}?step=model`}>Choose model</Link>
          </Button>
        }
      >
        Choose a model for this agent to start chatting.
      </BlockedBar>
    )
  } else if (llmKeys.isSuccess && !hasKey) {
    footer = (
      <BlockedBar action={<Button onClick={openApiKeys}>Add API key</Button>}>
        Add your {providerName} API key to start chatting.
      </BlockedBar>
    )
  } else {
    footer = (
      <Composer
        agentName={agent.name}
        value={draft}
        onChange={setDraft}
        onSend={send}
        // Send and Stop share one button: ignore Stop until the server has the message,
        // so a double click can't cancel a message before it is saved.
        onStop={() => openedRef.current && abortRef.current?.abort()}
        isStreaming={isStreaming}
        disabled={starting || llmKeys.isPending}
      />
    )
  }

  return (
    <div className="flex h-full min-w-0 flex-1 flex-col">
      <header className="flex flex-wrap items-center gap-x-3 gap-y-1 border-b px-4 py-3">
        <h1 className="truncate font-semibold">{agent.name}</h1>
        {agent.status === 'stopped' && <StatusBadge status="stopped" />}
        <span className="text-sm text-muted-foreground">
          {agent.llm_provider ? `${providerName} · ${modelName}` : 'No model chosen'}
        </span>
      </header>

      {sessionId && messages.isPending ? (
        <div className="mx-auto flex w-full max-w-3xl flex-1 flex-col gap-4 p-4" role="status" aria-label="Loading chat">
          <Skeleton className="ml-auto h-10 w-1/2" />
          <Skeleton className="h-20 w-2/3" />
          <Skeleton className="ml-auto h-10 w-1/3" />
        </div>
      ) : (
        <MessageList
          messages={shownMessages}
          streamingText={streamingText}
          isStreaming={isStreaming}
          error={shownError}
          onRetry={unanswered ? () => runTurn(sessionId, { retry: true }) : null}
          emptyHint={`Send a message to start chatting with ${agent.name}.`}
        />
      )}

      <div className="border-t">{footer}</div>
    </div>
  )
}

function Sidebar({ agents, agent, sessions, sessionId, onPickAgent, onDeleteSession, onNavigate }) {
  return (
    <div className="flex h-full flex-col gap-3">
      <AgentSelect agents={agents} value={agent?.id} onChange={onPickAgent} className="w-full" />
      {agent && (
        <>
          <Button variant="outline" asChild={agent.status === 'live'} disabled={agent.status !== 'live'} className="w-full">
            {agent.status === 'live' ? (
              <Link to={`/app/chat/${agent.id}`} onClick={onNavigate}>
                <Plus aria-hidden="true" /> New chat
              </Link>
            ) : (
              <>
                <Plus aria-hidden="true" /> New chat
              </>
            )}
          </Button>
          <div className="min-h-0 flex-1 overflow-y-auto">
            <SessionList
              agentId={agent.id}
              sessions={sessions}
              activeId={sessionId}
              onDelete={onDeleteSession}
              onNavigate={onNavigate}
            />
          </div>
        </>
      )}
    </div>
  )
}

export default function Chat() {
  const { agentId, sessionId } = useParams()
  const navigate = useNavigate()
  const agents = useAgents()
  const catalog = useModelCatalog()
  const sessions = useSessions(agentId)
  const deleteSession = useDeleteSession(agentId)
  const [sessionToDelete, setSessionToDelete] = useState(null)
  const [chatsOpen, setChatsOpen] = useState(false)

  if (agents.isPending) {
    return (
      <div className="flex h-full" role="status" aria-label="Loading chat">
        <div className="hidden w-64 flex-col gap-3 border-r p-3 md:flex">
          <Skeleton className="h-8" />
          <Skeleton className="h-8" />
        </div>
        <div className="flex-1 p-6">
          <Skeleton className="h-8 w-48" />
        </div>
      </div>
    )
  }
  if (agents.isError) {
    return (
      <CenteredNote>
        <p className="text-sm text-destructive">Your agents couldn&apos;t load.</p>
        <Button variant="outline" onClick={() => agents.refetch()}>
          Retry
        </Button>
      </CenteredNote>
    )
  }

  // Draft agents can't be chatted with. Stopped ones stay listed so their old chats are reachable.
  const chatAgents = agents.data.filter((a) => a.status !== 'draft')
  if (chatAgents.length === 0) {
    return (
      <CenteredNote>
        <p className="text-muted-foreground">You don&apos;t have a live agent yet.</p>
        <Button asChild>
          <Link to="/app/agents/new">
            <Plus aria-hidden="true" /> Create agent
          </Link>
        </Button>
      </CenteredNote>
    )
  }

  const agent = chatAgents.find((a) => a.id === agentId)
  const provider = catalog.data?.providers.find((p) => p.key === agent?.llm_provider)
  const providerName = provider?.name ?? agent?.llm_provider
  const modelName = provider?.models.find((m) => m.id === agent?.llm_model)?.name ?? agent?.llm_model

  function confirmDeleteSession() {
    const session = sessionToDelete
    deleteSession.mutate(session.id, {
      onSuccess: () => {
        toast.success('Chat deleted')
        if (session.id === sessionId) navigate(`/app/chat/${agentId}`, { replace: true })
      },
      onError: (err) => toast.error(err.message),
      onSettled: () => setSessionToDelete(null),
    })
  }

  const sidebarProps = {
    agents: chatAgents,
    agent,
    sessions,
    sessionId,
    onPickAgent: (id) => navigate(`/app/chat/${id}`),
    onDeleteSession: setSessionToDelete,
  }

  return (
    <div className="flex h-full flex-col md:flex-row">
      <aside className="hidden w-64 shrink-0 border-r p-3 md:block">
        <Sidebar {...sidebarProps} />
      </aside>

      {/* Small screens: the agent picker stays visible and the chat list opens as a drawer. */}
      <div className="flex items-center gap-2 border-b p-2 md:hidden">
        <AgentSelect agents={chatAgents} value={agent?.id} onChange={sidebarProps.onPickAgent} className="min-w-0 flex-1" />
        {agent && (
          <Button variant="outline" onClick={() => setChatsOpen(true)}>
            <MessagesSquare aria-hidden="true" /> Chats
          </Button>
        )}
      </div>
      <Sheet open={chatsOpen} onOpenChange={setChatsOpen}>
        <SheetContent side="left" className="w-72 p-3">
          <SheetHeader className="p-0 pt-1">
            <SheetTitle>Chats</SheetTitle>
            <SheetDescription className="sr-only">Pick an agent and one of its chats</SheetDescription>
          </SheetHeader>
          <Sidebar {...sidebarProps} onNavigate={() => setChatsOpen(false)} />
        </SheetContent>
      </Sheet>

      <section className="min-h-0 min-w-0 flex-1">
        {!agentId ? (
          <CenteredNote>
            <p className="text-muted-foreground">Pick an agent to start chatting.</p>
          </CenteredNote>
        ) : !agent ? (
          <CenteredNote>
            <p className="text-sm text-destructive">This agent isn&apos;t available to chat with.</p>
            <Button variant="outline" asChild>
              <Link to="/app/chat">Pick another agent</Link>
            </Button>
          </CenteredNote>
        ) : (
          // Keyed so each chat starts with a clean message box and streaming state.
          <ChatThread
            key={`${agent.id}:${sessionId ?? 'new'}`}
            agent={agent}
            sessionId={sessionId}
            providerName={providerName}
            modelName={modelName}
          />
        )}
      </section>

      <AlertDialog
        open={Boolean(sessionToDelete)}
        onOpenChange={(open) => !open && !deleteSession.isPending && setSessionToDelete(null)}
      >
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>Delete this chat?</AlertDialogTitle>
            <AlertDialogDescription>
              &ldquo;{sessionToDelete?.title}&rdquo; and its messages will be deleted. This can&apos;t be undone.
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel disabled={deleteSession.isPending}>Keep chat</AlertDialogCancel>
            <AlertDialogAction
              variant="destructive"
              disabled={deleteSession.isPending}
              onClick={(event) => {
                event.preventDefault() // keep the dialog open until the delete finishes
                confirmDeleteSession()
              }}
            >
              Delete chat
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </div>
  )
}
