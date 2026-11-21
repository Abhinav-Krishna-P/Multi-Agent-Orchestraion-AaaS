import { Loader2, TriangleAlert } from 'lucide-react'
import { useNavigate } from 'react-router-dom'
import { toast } from 'sonner'
import { StatusBadge } from '@/components/StatusBadge'
import { Alert, AlertDescription } from '@/components/ui/alert'
import { Button } from '@/components/ui/button'
import { useDeployAgent, useDocuments, useIntegrations, useLlmKeys, useModelCatalog, usePersonas } from '@/lib/queries'

function SummaryRow({ label, onEdit, children }) {
  return (
    <div className="flex items-start gap-4 p-4">
      <div className="min-w-0 flex-1">
        <dt className="text-sm text-muted-foreground">{label}</dt>
        <dd className="mt-0.5 text-sm">{children}</dd>
      </div>
      <Button variant="link" className="h-auto p-0" onClick={onEdit} aria-label={`Edit ${label.toLowerCase()}`}>
        Edit
      </Button>
    </div>
  )
}

export default function Deploy({ agent, onBack, goTo }) {
  const navigate = useNavigate()
  const personas = usePersonas()
  const catalog = useModelCatalog()
  const llmKeys = useLlmKeys()
  const deploy = useDeployAgent()
  const documents = useDocuments(agent.id)

  const persona = personas.data?.find((p) => p.key === agent.persona_key)
  const provider = catalog.data?.providers.find((p) => p.key === agent.llm_provider)
  const modelName = provider?.models.find((m) => m.id === agent.llm_model)?.name ?? agent.llm_model
  const hasBehavior = Boolean(agent.system_prompt.trim())
  const hasKey = llmKeys.data?.some((saved) => saved.provider === agent.llm_provider)
  const isLive = agent.status === 'live'

  // Warnings, not blockers: the agent can be deployed and finished later.
  const warnings = []
  if (!agent.llm_provider) warnings.push('Choose a model before chatting.')
  else if (llmKeys.data && !hasKey) warnings.push('Add your API key before chatting.')
  const documentCount = documents.data?.length ?? 0
  const connectedApps = (useIntegrations(agent.id).data?.apps ?? []).filter((app) => app.status === 'active')
  const indexing = documents.data?.some((doc) => doc.status === 'pending' || doc.status === 'processing')
  if (agent.kb_enabled && indexing) warnings.push('Some documents are still being indexed.')
  if (agent.kb_enabled && documents.data && documentCount === 0) {
    warnings.push('The knowledge base is on but has no documents yet.')
  }

  function deployAgent() {
    deploy.mutate(agent.id, {
      onSuccess: () => {
        toast.success(`${agent.name} is live`, {
          action: { label: 'Start chatting', onClick: () => navigate(`/app/chat/${agent.id}`) },
        })
        navigate('/app/agents')
      },
    })
  }

  function saveChanges() {
    // Every step already saved its own changes; this only confirms and leaves the wizard.
    toast.success('Changes saved')
    navigate('/app/agents')
  }

  return (
    <div className="flex flex-col gap-6">
      <dl className="divide-y rounded-xl border">
        <SummaryRow label="Basics" onEdit={() => goTo('basics')}>
          <span className="flex flex-wrap items-center gap-2">
            <span className="font-medium">{agent.name}</span>
            <StatusBadge status={agent.status} />
          </span>
          {agent.description && <span className="mt-1 block text-muted-foreground">{agent.description}</span>}
        </SummaryRow>
        <SummaryRow label="Behavior" onEdit={() => goTo('behavior')}>
          {hasBehavior ? (persona?.name ?? 'Custom prompt') : <span className="text-muted-foreground">Not chosen yet</span>}
        </SummaryRow>
        <SummaryRow label="Model" onEdit={() => goTo('model')}>
          {agent.llm_provider ? (
            `${provider?.name ?? agent.llm_provider} · ${modelName}`
          ) : (
            <span className="text-muted-foreground">Not chosen yet</span>
          )}
        </SummaryRow>
        <SummaryRow label="Knowledge" onEdit={() => goTo('knowledge')}>
          {agent.kb_enabled ? `On · ${documentCount} ${documentCount === 1 ? 'document' : 'documents'}` : 'Off'}
        </SummaryRow>
        <SummaryRow label="Tools" onEdit={() => goTo('tools')}>
          {agent.tools.length === 0 ? 'None' : `${agent.tools.length} ${agent.tools.length === 1 ? 'tool' : 'tools'}`}
        </SummaryRow>
        <SummaryRow label="Apps" onEdit={() => goTo('apps')}>
          {connectedApps.length === 0 ? 'None' : connectedApps.map((app) => app.name).join(', ')}
        </SummaryRow>
      </dl>

      {!hasBehavior && (
        <Alert variant="destructive">
          <TriangleAlert aria-hidden="true" />
          <AlertDescription>Choose a behavior before you deploy this agent.</AlertDescription>
        </Alert>
      )}
      {hasBehavior &&
        warnings.map((warning) => (
          <Alert key={warning} className="border-amber-500/30 bg-amber-500/10 text-amber-200">
            <TriangleAlert aria-hidden="true" />
            <AlertDescription className="text-amber-200">{warning}</AlertDescription>
          </Alert>
        ))}

      <div className="flex flex-col gap-3 border-t pt-4">
        {deploy.error && (
          <p role="alert" className="text-sm text-destructive">
            {deploy.error.message}
          </p>
        )}
        <div className="flex items-center gap-2">
          <Button variant="outline" onClick={onBack} disabled={deploy.isPending}>
            Back
          </Button>
          <div className="flex-1" />
          {isLive ? (
            <Button onClick={saveChanges}>Save changes</Button>
          ) : (
            <Button onClick={deployAgent} disabled={deploy.isPending || !hasBehavior}>
              {deploy.isPending && <Loader2 className="animate-spin" aria-hidden="true" />}
              Deploy agent
            </Button>
          )}
        </div>
      </div>
    </div>
  )
}
