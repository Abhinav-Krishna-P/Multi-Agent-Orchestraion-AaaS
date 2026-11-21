import { useQueryClient } from '@tanstack/react-query'
import { CircleCheck, Loader2, Plus, RotateCcw, Workflow } from 'lucide-react'
import { useEffect, useState } from 'react'
import { Link, useNavigate, useParams, useSearchParams } from 'react-router-dom'
import { toast } from 'sonner'
import { AgentSelect } from '@/components/AgentSelect'
import { AutomationList } from '@/components/automations/AutomationList'
import { Composer } from '@/components/chat/Composer'
import { MessageList } from '@/components/chat/MessageList'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Skeleton } from '@/components/ui/skeleton'
import { Tabs } from '@/components/ui/tabs'
import { keys, useAgents, useAutomationConversation, useAutomations, useMessages, useStartAutomationConversation } from '@/lib/queries'
import { INTERRUPTED, decisionText, useChatTurn } from '@/lib/useChatTurn'
import { cn } from '@/lib/utils'

const STOPPED_NOTE = 'Deploy this agent to describe new automations.'
const COMPOSER_ID = 'describe-composer'
const EXAMPLES = [
  'Every morning at 9, email me the USD to INR rate',
  "Every Friday at 5 pm, email me a summary of this week's news about AI",
  'Whenever I get a new email from my manager, email me a one-line summary',
]

function Note({ children, action }) {
  return (
    <div className="flex flex-1 flex-col items-center justify-center gap-3 p-6 text-center text-sm text-muted-foreground">
      <p>{children}</p>
      {action}
    </div>
  )
}

/** The describe chat's box: title, an optional action, then the chat itself. It fills the Create tab. */
function Frame({ action, children }) {
  return (
    <section className="flex min-h-0 flex-1 flex-col rounded-xl border bg-background" aria-labelledby="describe-heading">
      <header className="flex items-center justify-between gap-3 border-b px-4 py-2">
        <h2 id="describe-heading" className="py-1.5 text-sm font-semibold">
          Describe your automation
        </h2>
        {action}
      </header>
      {children}
    </section>
  )
}

/** Shown in an empty conversation: example requests that fill the message box, so they can be edited before sending. */
function Examples({ onPick }) {
  return (
    <div className="flex w-full max-w-md flex-col items-center gap-3">
      <p>Say what should happen and when, or start from an example:</p>
      <ul className="flex w-full flex-col gap-2">
        {EXAMPLES.map((text) => (
          <li key={text}>
            <Button
              variant="outline"
              className="h-auto w-full justify-start py-2 text-left font-normal whitespace-normal"
              onClick={() => onPick(text)}
            >
              {text}
            </Button>
          </li>
        ))}
      </ul>
    </div>
  )
}

function DescribeThread({ agent, sessionId, onStartOver, starting, onViewList }) {
  const client = useQueryClient()
  const messages = useMessages(sessionId)
  const [draft, setDraft] = useState('')
  const [created, setCreated] = useState(null) // the name of the automation that just went live
  const live = agent.status === 'live'
  const timezone = Intl.DateTimeFormat().resolvedOptions().timeZone || 'UTC'
  const { runTurn, stop, isStreaming, pendingUserText, streamingText, streamingTools, streamingSources, error, setError } =
    useChatTurn({ agentId: agent.id, sessionId, extraBody: { timezone }, onFailure: reportFailure })

  function reportFailure(failure, body) {
    if (failure.status === 401) return // signed out; the app is already leaving this page
    const saved = client.getQueryData(keys.messages(sessionId)) ?? []
    const unanswered = saved[saved.length - 1]?.role === 'user'
    // Give the text back whenever it was not saved, instead of losing it.
    if (body.message && (failure.status >= 400 || !unanswered)) setDraft(body.message)
    if (failure.code === 'agent_not_live') client.invalidateQueries({ queryKey: keys.agents })
    if (failure.code === 'reply_in_progress') return toast.error(failure.message)
    // Only the server's own errors carry a code; anything else is a dropped connection.
    setError({ message: failure.code ? failure.message : INTERRUPTED.message })
  }

  function send(text) {
    setDraft('')
    setCreated(null)
    runTurn({ message: text })
  }

  function pickExample(text) {
    setDraft(text)
    document.getElementById(COMPOSER_ID)?.focus() // the new text lands with the caret at its end
  }

  async function decide(message, decision) {
    setCreated(null)
    await runTurn({ approval: { message_id: message.id, decision } }, decisionText(message.approval, decision))
    if (decision !== 'approve') return
    client.invalidateQueries({ queryKey: keys.automations(agent.id) })
    // The reloaded card tells whether it really went live, or was approved but couldn't be set up.
    const answered = client.getQueryData(keys.messages(sessionId))?.find((m) => m.id === message.id)?.approval
    if (answered?.status === 'approved' && answered.outcome !== 'failed') setCreated(answered.name)
  }

  const startOver = (
    <Button variant="outline" size="sm" onClick={onStartOver} disabled={!live || isStreaming || starting}>
      {starting ? <Loader2 className="animate-spin" aria-hidden="true" /> : <RotateCcw aria-hidden="true" />}
      Start over
    </Button>
  )

  if (messages.isError) {
    return (
      <Frame action={startOver}>
        <Note
          action={
            <Button variant="outline" size="sm" onClick={() => messages.refetch()}>
              Retry
            </Button>
          }
        >
          This conversation couldn&apos;t load.
        </Note>
      </Frame>
    )
  }

  const saved = messages.data ?? []
  const shown = pendingUserText ? [...saved, { id: 'pending', role: 'user', content: pendingUserText }] : saved
  const unanswered = !isStreaming && saved[saved.length - 1]?.role === 'user'
  const shownError = error ?? (unanswered ? { message: "This message didn't get a reply." } : null)

  return (
    <Frame action={startOver}>
      {messages.isPending ? (
        <div className="flex flex-1 flex-col gap-4 p-4" role="status" aria-label="Loading conversation">
          <Skeleton className="ml-auto h-10 w-1/2" />
          <Skeleton className="h-20 w-2/3" />
        </div>
      ) : (
        <MessageList
          messages={shown}
          onSendForm={send}
          onDecide={decide}
          formDisabled={isStreaming || !live}
          streamingText={streamingText}
          streamingTools={streamingTools}
          streamingSources={streamingSources}
          isStreaming={isStreaming}
          error={shownError}
          onRetry={unanswered && live ? () => runTurn({ retry: true }) : null}
          emptyHint={live ? <Examples onPick={pickExample} /> : STOPPED_NOTE}
        />
      )}
      {created && (
        <div role="status" className="flex flex-wrap items-center justify-between gap-2 border-t bg-green-500/10 px-4 py-2">
          <p className="flex min-w-0 items-center gap-1.5 text-sm text-green-400">
            <CircleCheck className="size-4 shrink-0" aria-hidden="true" />
            <span className="break-words">&ldquo;{created}&rdquo; is live.</span>
          </p>
          <Button variant="outline" size="sm" onClick={onViewList}>
            View in Your automations
          </Button>
        </div>
      )}
      <div className="border-t">
        {live ? (
          <Composer
            id={COMPOSER_ID}
            agentName={agent.name}
            value={draft}
            onChange={setDraft}
            onSend={send}
            onStop={stop}
            isStreaming={isStreaming}
            disabled={messages.isPending}
            autoFocus={false}
          />
        ) : (
          <p className="p-4 text-sm text-muted-foreground">{STOPPED_NOTE}</p>
        )}
      </div>
    </Frame>
  )
}

function DescribeChat({ agent, onViewList }) {
  const conversation = useAutomationConversation(agent.id)
  const start = useStartAutomationConversation(agent.id)
  const live = agent.status === 'live'
  const begin = () => start.mutate(undefined, { onError: (err) => toast.error(err.message) })

  if (conversation.isPending) {
    return (
      <Frame>
        <div className="flex flex-1 flex-col gap-4 p-4" role="status" aria-label="Loading conversation">
          <Skeleton className="h-20 w-2/3" />
        </div>
      </Frame>
    )
  }
  if (conversation.isError) {
    return (
      <Frame>
        <Note
          action={
            <Button variant="outline" size="sm" onClick={() => conversation.refetch()}>
              Retry
            </Button>
          }
        >
          The conversation couldn&apos;t load.
        </Note>
      </Frame>
    )
  }
  if (!conversation.data) {
    return (
      <Frame>
        <Note
          action={
            live && (
              <Button onClick={begin} disabled={start.isPending}>
                {start.isPending && <Loader2 className="animate-spin" aria-hidden="true" />}
                Start
              </Button>
            )
          }
        >
          {live ? `Describe a job for ${agent.name} to do on its own, on a schedule or when something happens.` : STOPPED_NOTE}
        </Note>
      </Frame>
    )
  }
  return (
    // Keyed so a new conversation starts with a clean message box and streaming state.
    <DescribeThread
      key={conversation.data.id}
      agent={agent}
      sessionId={conversation.data.id}
      onStartOver={begin}
      starting={start.isPending}
      onViewList={onViewList}
    />
  )
}

export default function Automations() {
  const { agentId } = useParams()
  const navigate = useNavigate()
  const [params, setParams] = useSearchParams()
  const tab = params.get('tab') === 'create' ? 'create' : 'list'
  const agents = useAgents()
  // Stopped agents stay pickable so their (turned-off) automations can be seen and deleted.
  const pickable = (agents.data ?? []).filter((a) => a.status !== 'draft')
  const agent = pickable.find((a) => a.id === agentId)
  const automations = useAutomations(agent?.id) // the same query as the list: the count follows it

  const selectTab = (value) => setParams(value === 'create' ? { tab: 'create' } : {}, { replace: true })
  // From a button inside a panel that is about to hide: keep focus on the page, on the new tab.
  function goToTab(value) {
    selectTab(value)
    document.getElementById(`automations-tab-${value}`)?.focus()
  }

  // With no agent in the address, show the first live one.
  const firstId = (pickable.find((a) => a.status === 'live') ?? pickable[0])?.id
  useEffect(() => {
    if (!agentId && firstId) navigate({ pathname: `/app/automations/${firstId}`, search: params.toString() }, { replace: true })
  }, [agentId, firstId, navigate, params])

  const tabs = [
    {
      value: 'list',
      label: (
        <>
          Your automations
          {automations.data && (
            <Badge variant="secondary" className="tabular-nums">
              {automations.data.length}
            </Badge>
          )}
        </>
      ),
    },
    {
      value: 'create',
      label: (
        <>
          <Plus className="size-4" aria-hidden="true" /> Create automation
        </>
      ),
    },
  ]

  let body
  if (agents.isPending) {
    body = (
      <div className="flex flex-col gap-4" role="status" aria-label="Loading automations">
        <Skeleton className="h-10" />
        <Skeleton className="h-32" />
      </div>
    )
  } else if (agents.isError) {
    body = (
      <div className="flex flex-col items-start gap-3 rounded-xl border p-6">
        <p className="text-sm text-destructive">Your agents couldn&apos;t load.</p>
        <Button variant="outline" onClick={() => agents.refetch()}>
          Retry
        </Button>
      </div>
    )
  } else if (pickable.length === 0) {
    body = (
      <div className="flex flex-col items-center gap-3 rounded-xl border border-dashed p-10 text-center">
        <p className="text-sm text-muted-foreground">Deploy an agent to give it automations.</p>
        <Button asChild>
          <Link to="/app/agents/new">
            <Plus aria-hidden="true" /> Create agent
          </Link>
        </Button>
      </div>
    )
  } else if (agentId && !agent) {
    body = (
      <p className="rounded-xl border p-6 text-sm text-muted-foreground">
        This agent isn&apos;t available. Pick another one above.
      </p>
    )
  } else if (agent) {
    body = (
      <Tabs
        id="automations"
        label="Automations"
        tabs={tabs}
        value={tab}
        onChange={selectTab}
        className={cn(tab === 'create' && 'flex min-h-0 flex-1 flex-col')}
      >
        {/* Both stay mounted, so a reply still streaming in the describe chat isn't lost on a tab switch. */}
        <div className={cn(tab !== 'list' && 'hidden')}>
          <AutomationList agent={agent} onCreate={() => goToTab('create')} />
        </div>
        <div className={tab === 'create' ? 'flex min-h-0 flex-1 flex-col' : 'hidden'}>
          <DescribeChat key={agent.id} agent={agent} onViewList={() => goToTab('list')} />
        </div>
      </Tabs>
    )
  }

  return (
    // On the Create tab the page is exactly the window's height, so the chat scrolls inside and its box stays at the bottom.
    <div className={cn('flex flex-col gap-4 p-4 md:p-6', agent && tab === 'create' && 'h-full min-h-[32rem]')}>
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div className="min-w-0">
          <h1 className="flex items-center gap-2 text-2xl font-semibold">
            <Workflow className="size-6 text-primary" aria-hidden="true" /> Automations
          </h1>
          <p className="mt-1 text-sm text-muted-foreground">
            Jobs your agent runs on its own — on a schedule or when something happens.
          </p>
        </div>
        {pickable.length > 0 && (
          <AgentSelect
            agents={pickable}
            value={agent?.id}
            onChange={(id) => navigate({ pathname: `/app/automations/${id}`, search: params.toString() })}
            className="w-full sm:w-56"
          />
        )}
      </div>
      {body}
    </div>
  )
}
