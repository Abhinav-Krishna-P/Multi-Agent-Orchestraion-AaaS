export interface Source {
  [key: string]: unknown
}

export interface ToolUse {
  name: string
  ok: boolean
  result: unknown
  overridden?: string[]
}

export interface RunResult {
  id: string
  agent_id: string
  reply: string
  sources: Source[]
  tools_used: ToolUse[]
  duration_ms: number
}

export class AgentError extends Error {
  constructor(
    public status: number,
    public code: string,
    message: string,
    public retryAfter: number | null = null,
  ) {
    super(message)
    this.name = 'AgentError'
  }
}

export class Agent {
  private apiKey: string
  private baseUrl: string

  constructor(options: { apiKey: string; baseUrl?: string }) {
    this.apiKey = options.apiKey
    this.baseUrl = (options.baseUrl ?? 'http://localhost:8000').replace(/\/+$/, '')
  }

  async run(message: string): Promise<RunResult> {
    const response = await fetch(this.baseUrl + '/v1/run', {
      method: 'POST',
      headers: { Authorization: 'Bearer ' + this.apiKey, 'Content-Type': 'application/json' },
      body: JSON.stringify({ message }),
      signal: AbortSignal.timeout(200_000),
    })
    if (response.ok) return (await response.json()) as RunResult
    let code = 'http_error'
    let msg = `HTTP ${response.status}`
    try {
      const detail = ((await response.json()) as { detail?: { code?: unknown; message?: unknown } }).detail
      if (typeof detail?.code === 'string') code = detail.code
      if (typeof detail?.message === 'string') msg = detail.message
    } catch {
      // not the API's JSON error shape: keep the generic code
    }
    const retry = response.headers.get('Retry-After')
    throw new AgentError(response.status, code, msg, retry && /^\d+$/.test(retry) ? Number(retry) : null)
  }
}
