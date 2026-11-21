/** "GitHub: Create an issue" becomes { app: 'GitHub', names: ['Create an issue'] }, in first-seen order. */
export function groupActions(actions) {
  const apps = new Map()
  for (const a of actions) {
    const at = a.indexOf(': ')
    const app = at > 0 ? a.slice(0, at) : 'Other'
    const name = at > 0 ? a.slice(at + 2) : a
    apps.set(app, [...(apps.get(app) ?? []), name])
  }
  return [...apps].map(([app, names]) => ({ app, names }))
}

export const plural = (n, word) => `${n} ${word}${n === 1 ? '' : 's'}`

/** "19 actions in GitHub and Gmail", naming at most three apps. */
export function actionSummary(actions) {
  const apps = groupActions(actions).map((g) => g.app)
  const shown = apps.slice(0, 3)
  const rest = apps.length - shown.length
  const list = rest > 0 ? [...shown, plural(rest, 'other app')] : shown
  const text = list.length > 1 ? `${list.slice(0, -1).join(', ')} and ${list.at(-1)}` : list[0]
  return `${plural(actions.length, 'action')} in ${text}`
}
