import { cn } from '@/lib/utils'

/**
 * An underlined tab row and the panel it controls. `tabs` is [{ value, label }], where a label may
 * hold an icon or a badge. Arrow keys, Home and End move between tabs; only the selected one is in
 * the Tab order. The row scrolls sideways when it doesn't fit (on a phone).
 */
export function Tabs({ id, label, tabs, value, onChange, children, className }) {
  const tabId = (tab) => `${id}-tab-${tab}`

  function onKeyDown(event, at) {
    const next = { ArrowRight: (at + 1) % tabs.length, ArrowLeft: (at + tabs.length - 1) % tabs.length, Home: 0, End: tabs.length - 1 }[event.key]
    if (next == null) return
    event.preventDefault()
    onChange(tabs[next].value)
    document.getElementById(tabId(tabs[next].value))?.focus()
  }

  return (
    <>
      {/* The bottom line is an inset shadow, not a border: the tabs' underline covers it without a
          negative margin, which a scrolling row would clip. */}
      <div className="flex shrink-0 gap-1 overflow-x-auto shadow-[inset_0_-1px_0_var(--color-border)]" role="tablist" aria-label={label}>
        {tabs.map((tab, at) => (
          <button
            key={tab.value}
            type="button"
            role="tab"
            id={tabId(tab.value)}
            aria-controls={`${id}-panel`}
            aria-selected={value === tab.value}
            tabIndex={value === tab.value ? 0 : -1}
            onClick={() => onChange(tab.value)}
            onKeyDown={(event) => onKeyDown(event, at)}
            className={cn(
              'inline-flex shrink-0 cursor-pointer items-center gap-1.5 border-b-2 px-4 py-2 text-sm whitespace-nowrap outline-none transition-colors focus-visible:ring-3 focus-visible:ring-ring/50 focus-visible:ring-inset',
              value === tab.value ? 'border-primary font-medium text-primary' : 'border-transparent text-muted-foreground hover:text-foreground',
            )}
          >
            {tab.label}
          </button>
        ))}
      </div>
      <div role="tabpanel" id={`${id}-panel`} aria-labelledby={tabId(value)} className={className}>
        {children}
      </div>
    </>
  )
}
