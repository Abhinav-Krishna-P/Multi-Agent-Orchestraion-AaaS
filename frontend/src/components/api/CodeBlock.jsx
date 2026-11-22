import { Check, Copy } from 'lucide-react'
import { Highlight, themes } from 'prism-react-renderer'
import { useEffect, useState } from 'react'

// prism-react-renderer bundles no PHP, Java, C# or shell grammar; clike still colours their strings, comments and keywords.
const GRAMMAR = { python: 'python', javascript: 'javascript', typescript: 'typescript', go: 'go' }

/** A dark code block: language name and Copy button in a header bar, highlighted code that scrolls sideways. */
export function CodeBlock({ code, language, label }) {
  const [copied, setCopied] = useState(false)

  useEffect(() => {
    if (!copied) return
    const timer = setTimeout(() => setCopied(false), 2000)
    return () => clearTimeout(timer)
  }, [copied])

  async function copy() {
    try {
      await navigator.clipboard.writeText(code)
      setCopied(true)
    } catch {
      // Clipboard blocked: the code is selectable.
    }
  }

  return (
    <div className="overflow-hidden rounded-xl border border-white/10 bg-[#0d1017]">
      <div className="flex items-center justify-between border-b border-white/10 bg-white/[0.04] py-1.5 pr-2 pl-4">
        <span className="text-xs text-zinc-400">{label}</span>
        <button
          type="button"
          onClick={copy}
          className="inline-flex cursor-pointer items-center gap-1.5 rounded-md px-2 py-1 text-xs text-zinc-300 outline-none hover:bg-white/10 hover:text-white focus-visible:ring-3 focus-visible:ring-ring/60"
        >
          {copied ? <Check className="size-3.5 text-green-400" aria-hidden="true" /> : <Copy className="size-3.5" aria-hidden="true" />}
          {copied ? 'Copied' : 'Copy'}
        </button>
        <span role="status" className="sr-only">
          {copied ? 'Code copied' : ''}
        </span>
      </div>
      <Highlight theme={themes.vsDark} code={code.replace(/\n$/, '')} language={GRAMMAR[language] ?? 'clike'}>
        {({ tokens, getLineProps, getTokenProps }) => (
          // tabIndex lets keyboard users scroll long lines.
          <pre tabIndex={0} className="overflow-x-auto p-4 font-mono text-[13px] leading-relaxed outline-none focus-visible:ring-2 focus-visible:ring-ring/60 focus-visible:ring-inset" style={{ background: 'transparent' }}>
            <code>
              {tokens.map((line, i) => (
                <div key={i} {...getLineProps({ line })}>
                  {line.map((token, k) => (
                    <span key={k} {...getTokenProps({ token })} />
                  ))}
                </div>
              ))}
            </code>
          </pre>
        )}
      </Highlight>
    </div>
  )
}
