// Server data hooks shared by several screens. Each query has one key, listed in `keys`.
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { api } from './api'

export const keys = {
  llmKeys: ['llm-keys'],
  models: ['llm-models'],
  personas: ['personas'],
  agents: ['agents'],
  agent: (id) => ['agents', id],
  sessions: (agentId) => ['sessions', agentId],
  session: (id) => ['session', id],
  messages: (sessionId) => ['messages', sessionId],
}

// --- LLM keys and models --------------------------------------------------------------

export function useLlmKeys() {
  return useQuery({ queryKey: keys.llmKeys, queryFn: () => api('/llm-keys') })
}

export function useSaveLlmKey() {
  const client = useQueryClient()
  return useMutation({
    mutationFn: ({ provider, apiKey }) => api(`/llm-keys/${provider}`, { method: 'PUT', body: { api_key: apiKey } }),
    onSuccess: () => client.invalidateQueries({ queryKey: keys.llmKeys }),
  })
}

export function useDeleteLlmKey() {
  const client = useQueryClient()
  return useMutation({
    mutationFn: (provider) => api(`/llm-keys/${provider}`, { method: 'DELETE' }),
    onSuccess: () => client.invalidateQueries({ queryKey: keys.llmKeys }),
  })
}

/** The fixed list of providers and their models. It never changes while the app is open. */
export function useModelCatalog() {
  return useQuery({ queryKey: keys.models, queryFn: () => api('/llm-models'), staleTime: Infinity })
}

export function usePersonas() {
  return useQuery({ queryKey: keys.personas, queryFn: () => api('/personas'), staleTime: Infinity })
}

// --- Agents ---------------------------------------------------------------------------

export function useAgents() {
  return useQuery({ queryKey: keys.agents, queryFn: () => api('/agents') })
}

export function useAgent(agentId) {
  return useQuery({
    queryKey: keys.agent(agentId),
    queryFn: () => api(`/agents/${agentId}`),
    enabled: Boolean(agentId),
  })
}

/** Runs an agent request, then refreshes the agent list and stores the returned agent. */
function useAgentMutation(mutationFn) {
  const client = useQueryClient()
  return useMutation({
    mutationFn,
    onSuccess: (agent) => {
      if (agent?.id) client.setQueryData(keys.agent(agent.id), agent)
      return client.invalidateQueries({ queryKey: keys.agents, exact: true })
    },
  })
}

export function useCreateAgent() {
  return useAgentMutation((body) => api('/agents', { method: 'POST', body }))
}

export function useUpdateAgent() {
  return useAgentMutation(({ id, ...body }) => api(`/agents/${id}`, { method: 'PATCH', body }))
}

export function useDeployAgent() {
  return useAgentMutation((id) => api(`/agents/${id}/deploy`, { method: 'POST' }))
}

export function useStopAgent() {
  return useAgentMutation((id) => api(`/agents/${id}/stop`, { method: 'POST' }))
}

export function useDeleteAgent() {
  const client = useQueryClient()
  return useMutation({
    mutationFn: (id) => api(`/agents/${id}`, { method: 'DELETE' }),
    onSuccess: (_data, id) => {
      client.removeQueries({ queryKey: keys.agent(id) })
      client.removeQueries({ queryKey: keys.sessions(id) })
      return client.invalidateQueries({ queryKey: keys.agents, exact: true })
    },
  })
}

// --- Chats ----------------------------------------------------------------------------

export function useSessions(agentId) {
  return useQuery({
    queryKey: keys.sessions(agentId),
    queryFn: () => api(`/agents/${agentId}/sessions`),
    enabled: Boolean(agentId),
  })
}

export function useCreateSession(agentId) {
  const client = useQueryClient()
  return useMutation({
    mutationFn: () => api(`/agents/${agentId}/sessions`, { method: 'POST' }),
    onSuccess: () => client.invalidateQueries({ queryKey: keys.sessions(agentId) }),
  })
}

export function useDeleteSession(agentId) {
  const client = useQueryClient()
  return useMutation({
    mutationFn: (sessionId) => api(`/sessions/${sessionId}`, { method: 'DELETE' }),
    onSuccess: (_data, sessionId) => {
      client.removeQueries({ queryKey: keys.messages(sessionId) })
      return client.invalidateQueries({ queryKey: keys.sessions(agentId) })
    },
  })
}

export function useMessages(sessionId) {
  return useQuery({
    queryKey: keys.messages(sessionId),
    queryFn: () => api(`/sessions/${sessionId}/messages`),
    enabled: Boolean(sessionId),
  })
}
