// The apps the backend offers (backend/app/integrations/composio.py APPS); an unknown one shows its slug.
const APP_NAMES = {
  gmail: 'Gmail',
  googlecalendar: 'Google Calendar',
  outlook: 'Outlook',
  googledrive: 'Google Drive',
  googledocs: 'Google Docs',
  googlesheets: 'Google Sheets',
  notion: 'Notion',
  slack: 'Slack',
  github: 'GitHub',
  linear: 'Linear',
  trello: 'Trello',
  hubspot: 'HubSpot',
}

const asText = (value) => (typeof value === 'string' ? value : JSON.stringify(value))
function settings(values) {
  const parts = Object.entries(values ?? {}).map(([key, value]) => `${key}: ${asText(value)}`)
  return parts.length ? ` · ${parts.join(', ')}` : ''
}

const words = (text) => String(text ?? '').toLowerCase().replace(/[^\p{L}\p{N}]+/gu, ' ').trim()
/** True when two texts say the same words, ignoring case and punctuation: the model's trigger_text adds nothing then. */
export const sameWords = (a, b) => words(a) === words(b)

/** "GITHUB_FIND_REPOSITORIES" -> "GitHub · Find repositories": the app prefix and _TRIGGER/_EVENT suffix dropped. */
function slugInWords(slug, app) {
  const text = String(slug ?? '').toLowerCase().replace(new RegExp(`^${app}_`), '').replace(/_(trigger|event)$/, '').replace(/_/g, ' ')
  return `${APP_NAMES[app] ?? app} · ${text.charAt(0).toUpperCase()}${text.slice(1)}`
}

/** The trigger's stored settings in plain words: what actually runs, whatever the model wrote in trigger_text. */
export function triggerSummary(kind, trigger, timezone = trigger?.timezone) {
  if (!trigger) return ''
  if (kind === 'schedule')
    return trigger.every_minutes ? `Every ${trigger.every_minutes} minutes` : `Cron ${trigger.cron} (${timezone ?? 'UTC'})`
  if (kind === 'event')
    return `${slugInWords(trigger.trigger_slug, trigger.app)}${settings(trigger.config)}`
  if (kind === 'watch') return `Checks ${slugInWords(trigger.action, trigger.app)} every 5 minutes${settings(trigger.arguments)}`
  return ''
}
