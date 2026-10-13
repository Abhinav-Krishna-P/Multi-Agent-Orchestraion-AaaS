import { BarChart3, MessageSquare, MoreHorizontal, Pencil, Play, Plus, Square, Trash2 } from 'lucide-react'
import { useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { toast } from 'sonner'
import { StatusBadge } from '@/components/StatusBadge'
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
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu'
import { Skeleton } from '@/components/ui/skeleton'
import { useAgents, useDeleteAgent, useDeployAgent, useModelCatalog, useStopAgent } from '@/lib/queries'

function modelLabel(agent, catalog) {
  if (!agent.llm_provider) return 'No model chosen'
  const provider = catalog?.providers.find((p) => p.key === agent.llm_provider)
  return `${provider?.name ?? agent.llm_provider} · ${agent.llm_model}`
}

function AgentRow({ agent, catalog, onDelete }) {
  const navigate = useNavigate()
  const deploy = useDeployAgent()
  const stop = useStopAgent()

  function start() {
    deploy.mutate(agent.id, {
      onSuccess: () => toast.success(`${agent.name} is live`),
      onError: (err) => toast.error(err.message),
    })
  }

  function stopAgent() {
    stop.mutate(agent.id, {
      onSuccess: () => toast.success(`${agent.name} is stopped`),
      onError: (err) => toast.error(err.message),
    })
  }

  return (
    <li className="flex items-start gap-4 p-4">
      <div className="min-w-0 flex-1">
        <div className="flex flex-wrap items-center gap-x-3 gap-y-1">
          <span className="truncate font-medium">{agent.name}</span>
          <StatusBadge status={agent.status} />
          <span className="text-sm text-muted-foreground">{modelLabel(agent, catalog)}</span>
        </div>
        {agent.description && <p className="mt-1 truncate text-sm text-muted-foreground">{agent.description}</p>}
      </div>

      <div className="flex shrink-0 items-center gap-1">
        <Button variant="outline" asChild>
          <Link to={`/app/agents/${agent.id}`}>
            <Pencil aria-hidden="true" /> Edit
          </Link>
        </Button>
        <DropdownMenu>
          <DropdownMenuTrigger asChild>
            <Button variant="ghost" size="icon" aria-label={`More actions for ${agent.name}`}>
              <MoreHorizontal aria-hidden="true" />
            </Button>
          </DropdownMenuTrigger>
          <DropdownMenuContent align="end" className="w-44">
            <DropdownMenuItem disabled={agent.status === 'draft'} onSelect={() => navigate(`/app/chat/${agent.id}`)}>
              <MessageSquare aria-hidden="true" /> Chat
            </DropdownMenuItem>
            <DropdownMenuItem onSelect={() => navigate(`/app/analytics/${agent.id}`)}>
              <BarChart3 aria-hidden="true" /> Analytics
            </DropdownMenuItem>
            {agent.status === 'live' && (
              <DropdownMenuItem onSelect={stopAgent}>
                <Square aria-hidden="true" /> Stop
              </DropdownMenuItem>
            )}
            {agent.status === 'stopped' && (
              <DropdownMenuItem onSelect={start}>
                <Play aria-hidden="true" /> Start
              </DropdownMenuItem>
            )}
            <DropdownMenuSeparator />
            <DropdownMenuItem variant="destructive" onSelect={() => onDelete(agent)}>
              <Trash2 aria-hidden="true" /> Delete
            </DropdownMenuItem>
          </DropdownMenuContent>
        </DropdownMenu>
      </div>
    </li>
  )
}

export default function AgentsList() {
  const agents = useAgents()
  const catalog = useModelCatalog()
  const deleteAgent = useDeleteAgent()
  const [toDelete, setToDelete] = useState(null)

  function confirmDelete() {
    const agent = toDelete
    deleteAgent.mutate(agent.id, {
      onSuccess: () => toast.success(`${agent.name} deleted`),
      onError: (err) => toast.error(err.message),
      onSettled: () => setToDelete(null),
    })
  }

  return (
    <div className="mx-auto flex max-w-4xl flex-col gap-6 p-6">
      <div className="flex items-center justify-between gap-4">
        <h1 className="text-2xl font-semibold">Your agents</h1>
        {agents.data?.length > 0 && (
          <Button asChild>
            <Link to="/app/agents/new">
              <Plus aria-hidden="true" /> Create agent
            </Link>
          </Button>
        )}
      </div>

      {agents.isPending ? (
        <div className="flex flex-col gap-3" role="status" aria-label="Loading your agents">
          <Skeleton className="h-18" />
          <Skeleton className="h-18" />
          <Skeleton className="h-18" />
        </div>
      ) : agents.isError ? (
        <div className="flex flex-col items-start gap-3 rounded-xl border p-6">
          <p className="text-sm text-destructive">Your agents couldn&apos;t load.</p>
          <Button variant="outline" onClick={() => agents.refetch()}>
            Retry
          </Button>
        </div>
      ) : agents.data.length === 0 ? (
        <div className="flex flex-col items-center gap-4 rounded-xl border border-dashed p-12 text-center">
          <p className="text-muted-foreground">You don&apos;t have any agents yet. Create one to start chatting.</p>
          <Button asChild>
            <Link to="/app/agents/new">
              <Plus aria-hidden="true" /> Create agent
            </Link>
          </Button>
        </div>
      ) : (
        <ul className="divide-y rounded-xl border">
          {agents.data.map((agent) => (
            <AgentRow key={agent.id} agent={agent} catalog={catalog.data} onDelete={setToDelete} />
          ))}
        </ul>
      )}

      <AlertDialog open={Boolean(toDelete)} onOpenChange={(open) => !open && !deleteAgent.isPending && setToDelete(null)}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>Delete {toDelete?.name}?</AlertDialogTitle>
            <AlertDialogDescription>Its chats will be deleted too. This can&apos;t be undone.</AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel disabled={deleteAgent.isPending}>Keep agent</AlertDialogCancel>
            <AlertDialogAction
              variant="destructive"
              disabled={deleteAgent.isPending}
              onClick={(event) => {
                event.preventDefault() // keep the dialog open until the delete finishes
                confirmDelete()
              }}
            >
              Delete agent
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </div>
  )
}
