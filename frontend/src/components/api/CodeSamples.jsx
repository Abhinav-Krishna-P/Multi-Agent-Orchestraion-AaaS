import { useMemo, useState } from 'react'
import { CodeBlock } from '@/components/api/CodeBlock'
import { snippets } from '@/components/api/snippets'
import { Tabs } from '@/components/ui/tabs'
import { API_URL } from '@/lib/api'

// Tab id to highlighter language; ids not listed are the same word.
const LANGUAGE = { node: 'javascript', curl: 'bash' }

export function CodeSamples() {
  const samples = useMemo(() => snippets(API_URL), [])
  const [id, setId] = useState(samples[0].id)
  const sample = samples.find((s) => s.id === id)

  return (
    <section className="flex flex-col gap-3" aria-labelledby="api-use-heading">
      <h2 id="api-use-heading" className="text-lg font-semibold">
        Use it
      </h2>
      <Tabs id="api-samples" label="Code sample language" tabs={samples.map((s) => ({ value: s.id, label: s.label }))} value={id} onChange={setId} className="pt-3">
        <CodeBlock key={id} code={sample.code} language={LANGUAGE[id] ?? id} label={sample.label} />
      </Tabs>
      <p className="text-sm text-muted-foreground">Keep the key on your server. Never put it in browser or mobile-app code.</p>
    </section>
  )
}
