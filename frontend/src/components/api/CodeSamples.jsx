import { Check, Copy } from 'lucide-react'
import { useMemo, useState } from 'react'
import { snippets } from '@/components/api/snippets'
import { Button } from '@/components/ui/button'
import { Tabs } from '@/components/ui/tabs'
import { API_URL } from '@/lib/api'

export function CodeSamples() {
  const samples = useMemo(() => snippets(API_URL), [])
  const [id, setId] = useState(samples[0].id)
  const [copied, setCopied] = useState(false)
  const sample = samples.find((s) => s.id === id)

  async function copy() {
    try {
      await navigator.clipboard.writeText(sample.code)
      setCopied(true)
      setTimeout(() => setCopied(false), 2000)
    } catch {
      // Clipboard blocked: the text is selectable in the box.
    }
  }

  return (
    <section className="flex flex-col gap-3" aria-labelledby="api-use-heading">
      <h2 id="api-use-heading" className="text-lg font-semibold">
        Use it
      </h2>
      <Tabs
        id="api-samples"
        label="Code sample language"
        tabs={samples.map((s) => ({ value: s.id, label: s.label }))}
        value={id}
        onChange={(next) => {
          setId(next)
          setCopied(false)
        }}
        className="relative pt-3"
      >
        <Button variant="outline" size="sm" className="absolute top-5 right-2" onClick={copy}>
          {copied ? <Check aria-hidden="true" /> : <Copy aria-hidden="true" />} {copied ? 'Copied' : 'Copy'}
        </Button>
        <pre className="overflow-x-auto rounded-xl border bg-muted/50 p-4 pt-12 text-xs leading-relaxed">
          <code>{sample.code}</code>
        </pre>
      </Tabs>
      <p className="text-sm text-muted-foreground">Keep the key on your server. Never put it in browser or mobile-app code.</p>
    </section>
  )
}
