import { Check, Copy, ExternalLink, Star } from 'lucide-react'
import { useState } from 'react'
import { cn } from '@/lib/utils'
import { number, safeUrl } from './format'

/** An image from a service. It is left out, or replaced by `fallback`, when it has no usable address or fails to load. */
export function CardImage({ src, alt = '', className, fallback = null }) {
  const [failed, setFailed] = useState(false)
  const url = safeUrl(src)
  if (!url || failed) return fallback
  return (
    <img
      src={url}
      alt={alt}
      loading="lazy"
      referrerPolicy="no-referrer"
      className={className}
      onError={() => setFailed(true)}
    />
  )
}

/** A link to another site, in a new tab. With an unusable address it is plain content, not a dead link. */
export function ExtLink({ href, className, children, ...props }) {
  const url = safeUrl(href)
  if (!url) return <div className={className}>{children}</div>
  return (
    <a href={url} target="_blank" rel="noreferrer noopener" className={className} {...props}>
      {children}
    </a>
  )
}

/** "View on Amazon ↗" style action. */
export function Action({ href, children, className }) {
  if (!safeUrl(href)) return null
  return (
    <ExtLink
      href={href}
      className={cn(
        'inline-flex items-center gap-1 rounded-sm text-xs font-medium text-primary outline-none hover:underline focus-visible:ring-3 focus-visible:ring-ring/50',
        className,
      )}
    >
      {children}
      <ExternalLink className="size-3" aria-hidden="true" />
    </ExtLink>
  )
}

export function Stars({ rating, reviews }) {
  if (rating == null) return null
  return (
    <span className="flex shrink-0 items-center gap-1 text-xs whitespace-nowrap text-muted-foreground">
      <Star className="size-3.5 fill-amber-400 text-amber-400" aria-hidden="true" />
      <span className="font-medium text-foreground">{rating}</span>
      <span className="sr-only">out of 5</span>
      {reviews != null && <span>({number(reviews, { notation: 'compact' })})</span>}
    </span>
  )
}

/** The frame every card shares: which service it came from, and an optional link to see more there. */
export function Frame({ service, heading, link, linkLabel, children, className }) {
  return (
    <section className={cn('rounded-xl border bg-background', className)} aria-label={`${service} results`}>
      <header className="flex items-center justify-between gap-3 border-b px-4 py-2">
        <p className="min-w-0 truncate text-xs font-medium text-muted-foreground">
          {service}
          {heading && <span className="text-foreground"> · {heading}</span>}
        </p>
        <Action href={link} className="shrink-0">
          {linkLabel}
        </Action>
      </header>
      {children}
    </section>
  )
}

export function CopyButton({ text, label = 'Copy' }) {
  const [copied, setCopied] = useState(false)
  if (!navigator.clipboard) return null
  return (
    <button
      type="button"
      onClick={() =>
        navigator.clipboard.writeText(String(text)).then(() => {
          setCopied(true)
          setTimeout(() => setCopied(false), 1500)
        })
      }
      className="inline-flex cursor-pointer items-center gap-1 rounded-md border px-2 py-1 text-xs text-muted-foreground outline-none transition-colors hover:bg-muted hover:text-foreground focus-visible:ring-3 focus-visible:ring-ring/50"
    >
      {copied ? <Check className="size-3.5 text-green-700" aria-hidden="true" /> : <Copy className="size-3.5" aria-hidden="true" />}
      {copied ? 'Copied' : label}
    </button>
  )
}

/** A small labelled figure, used in the grids of the weather, stock and flight cards. */
export function Fact({ label, children, icon: Icon }) {
  if (children == null || children === '') return null
  return (
    <div className="min-w-0">
      <dt className="flex items-center gap-1 text-xs text-muted-foreground">
        {Icon && <Icon className="size-3.5" aria-hidden="true" />}
        {label}
      </dt>
      <dd className="truncate text-sm font-medium">{children}</dd>
    </div>
  )
}
