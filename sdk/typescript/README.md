# agentplatform (TypeScript / JavaScript)

Call one of your agents from your own code. Uses the built-in `fetch` (Node 18+), ESM with `.d.ts` types. Not published yet; install from the repo folder:

    npm install ./sdk/typescript

(Build first if `dist/` is missing: `cd sdk/typescript && npm install && npm run build`.)

## Use

```ts
import { Agent, AgentError } from 'agentplatform'

const agent = new Agent({ apiKey: process.env.AGENT_API_KEY!, baseUrl: 'http://localhost:8000' })
try {
  const result = await agent.run('What can you do?')
  console.log(result.reply)
} catch (err) {
  if (!(err instanceof AgentError)) throw err
  console.log(err.status, err.code, err.message, err.retryAfter)
}
```

`run` resolves to a `RunResult` (`id`, `agent_id`, `reply`, `sources`, `tools_used`, `duration_ms`). A failed call throws `AgentError` with `status`, `code`, `message` and `retryAfter` (seconds from the `Retry-After` header on a 429, otherwise `null`). The package does not retry. The timeout is 200 seconds.

## Keep the key secret

Read the key from an environment variable or a secret store. Never commit it, put it in a web page, or ship it in a mobile app.
