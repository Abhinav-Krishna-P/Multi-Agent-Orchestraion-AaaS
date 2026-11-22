import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'

/** Picks one of the user's agents. Draft agents can't be chatted with, so callers pass live and stopped ones. */
export function AgentSelect({ agents, value, onChange, className }) {
  return (
    <Select value={value ?? ''} onValueChange={onChange}>
      <SelectTrigger className={className} aria-label="Agent">
        <SelectValue placeholder="Pick an agent" />
      </SelectTrigger>
      <SelectContent>
        {agents.map((agent) => (
          <SelectItem key={agent.id} value={agent.id}>
            {agent.name}
            {agent.status === 'stopped' && ' (stopped)'}
          </SelectItem>
        ))}
      </SelectContent>
    </Select>
  )
}
