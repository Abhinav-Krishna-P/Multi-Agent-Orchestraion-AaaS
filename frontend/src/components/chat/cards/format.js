/**
 * Card data comes from the services the tools called, never from the agent's own text. Even
 * so, an address is only ever used if it is a plain web address.
 */
export function safeUrl(value) {
  if (typeof value !== 'string') return undefined
  try {
    const url = new URL(value)
    return url.protocol === 'https:' || url.protocol === 'http:' ? url.href : undefined
  } catch {
    return undefined
  }
}

if (import.meta.env.DEV) {
  console.assert(safeUrl('https://a.b/c') === 'https://a.b/c', 'safeUrl: https passes')
  for (const bad of ['javascript:alert(1)', 'data:text/html,x', '//a.b', '', undefined, 42]) {
    console.assert(safeUrl(bad) === undefined, `safeUrl: rejects ${String(bad)}`)
  }
}

export function number(value, options) {
  return typeof value === 'number' ? new Intl.NumberFormat(undefined, options).format(value) : value
}

/** An amount with its currency sign; just the number when the currency code is not one the browser knows. */
export function money(value, currency) {
  if (typeof value !== 'number') return value
  try {
    return new Intl.NumberFormat(undefined, { style: 'currency', currency, maximumFractionDigits: 2 }).format(value)
  } catch {
    return [number(value), currency].filter(Boolean).join(' ')
  }
}
