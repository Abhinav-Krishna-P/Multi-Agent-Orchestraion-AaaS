import {
  Calculator,
  Clock,
  CloudSun,
  Coins,
  Globe,
  LayoutGrid,
  MapPin,
  Newspaper,
  Plane,
  Search,
  ShoppingBag,
  Wrench,
} from 'lucide-react'
import { useState } from 'react'
import { Button } from '@/components/ui/button'
import { Checkbox } from '@/components/ui/checkbox'
import { Input } from '@/components/ui/input'
import { Popover, PopoverContent, PopoverTrigger } from '@/components/ui/popover'
import { Skeleton } from '@/components/ui/skeleton'
import { Switch } from '@/components/ui/switch'
import { useSetAgentTools, useToolCatalog } from '@/lib/queries'
import { cn } from '@/lib/utils'
import { StepFooter } from './StepFooter'

// Each service's own logo, stored in public/logos. Built-in tools have no service, so
// they get an icon instead.
const LOGOS = {
  'Google Search': 'google',
  'Google Books': 'google',
  'Google Images': 'google',
  'Google Translate': 'google-translate',
  'Google News': 'google-news',
  'Google Maps': 'google-maps',
  'Google Shopping': 'google-shopping',
  'Google Flights': 'google-flights',
  Airbnb: 'airbnb',
  Amazon: 'amazon',
  'Open-Meteo': 'open-meteo',
  Frankfurter: 'frankfurter',
  Finnhub: 'finnhub',
}
const BUILT_IN_ICONS = { Calculator, Clock }
const CATEGORY_ICONS = {
  Basics: Calculator,
  'Search and knowledge': Globe,
  Weather: CloudSun,
  News: Newspaper,
  'Money and markets': Coins,
  Travel: Plane,
  Places: MapPin,
  Shopping: ShoppingBag,
}

/** The catalog lists tools by category; the page shows one card per service within each category. */
function toApps(groups) {
  const apps = []
  for (const group of groups) {
    for (const tool of group.tools) {
      let app = apps.find((a) => a.category === group.name && a.name === tool.app)
      if (!app) {
        app = { category: group.name, name: tool.app, tools: [] }
        apps.push(app)
      }
      app.tools.push(tool)
    }
  }
  return apps
}

function matches(app, query) {
  const text = [app.name, app.category, ...app.tools.flatMap((tool) => [tool.label, tool.description])].join(' ')
  return text.toLowerCase().includes(query.trim().toLowerCase())
}

function AppLogo({ name }) {
  const Icon = BUILT_IN_ICONS[name] ?? Wrench
  return (
    <span className="flex size-10 shrink-0 items-center justify-center overflow-hidden rounded-md">
      {LOGOS[name] ? (
        <img src={`/logos/${LOGOS[name]}.png`} alt="" className="size-9 object-contain" />
      ) : (
        <Icon className="size-5 text-primary" aria-hidden="true" />
      )}
    </span>
  )
}

function AppCard({ app, selected, onToggle }) {
  const id = `app-${app.category}-${app.name}`.replace(/\s+/g, '-')
  const names = app.tools.map((tool) => tool.name)
  const on = names.filter((name) => selected.has(name)).length
  const allOn = on === names.length

  return (
    // A plain card with a hairline border. The switch alone shows whether a service is on.
    <div className="flex flex-col gap-3 rounded-md border bg-background p-4 transition-colors hover:border-foreground/25">
      <div className="flex items-center gap-3">
        <AppLogo name={app.name} />
        <div className="min-w-0 flex-1">
          <label htmlFor={id} className="block cursor-pointer truncate text-sm font-semibold">
            {app.name}
          </label>
          <p className="mt-0.5 flex items-center gap-1.5 text-xs text-muted-foreground">
            <Wrench className="size-3.5 shrink-0" aria-hidden="true" />
            {names.length} {names.length === 1 ? 'tool' : 'tools'}
            {on > 0 && !allOn && ` · ${on} on`}
          </p>
        </div>
        <Switch id={id} checked={allOn} onCheckedChange={(checked) => onToggle(names, checked)} />
      </div>
      <div className="flex items-end justify-between gap-3">
        <p className="line-clamp-2 text-xs text-muted-foreground">
          {app.tools.length === 1 ? app.tools[0].description : app.tools.map((tool) => tool.label).join(', ')}
        </p>
        {app.tools.length > 1 && (
          <Popover>
            <PopoverTrigger asChild>
              <Button type="button" variant="outline" size="xs" aria-label={`Manage ${app.name} tools`}>
                Manage
              </Button>
            </PopoverTrigger>
            <PopoverContent align="end" className="w-72">
              <p className="mb-2 text-sm font-medium">{app.name} tools</p>
              <div className="flex flex-col gap-3">
                {app.tools.map((tool) => (
                  <div key={tool.name} className="flex items-start gap-2">
                    <Checkbox
                      id={`tool-${tool.name}`}
                      checked={selected.has(tool.name)}
                      onCheckedChange={(checked) => onToggle([tool.name], checked === true)}
                      className="mt-0.5"
                    />
                    <label htmlFor={`tool-${tool.name}`} className="cursor-pointer text-sm">
                      {tool.label}
                      <span className="block text-xs text-muted-foreground">{tool.description}</span>
                    </label>
                  </div>
                ))}
              </div>
            </PopoverContent>
          </Popover>
        )}
      </div>
    </div>
  )
}

function CategoryList({ categories, apps, active, onPick, className }) {
  const options = [{ name: null, label: 'All categories', icon: LayoutGrid, count: apps.length }].concat(
    categories.map((name) => ({
      name,
      label: name,
      icon: CATEGORY_ICONS[name] ?? Wrench,
      count: apps.filter((app) => app.category === name).length,
    })),
  )
  return (
    <ul className={className}>
      {options.map((option) => (
        <li key={option.label}>
          <button
            type="button"
            aria-pressed={active === option.name}
            onClick={() => onPick(option.name)}
            className={cn(
              'flex w-full cursor-pointer items-center gap-2 rounded-md px-2.5 py-2 text-left text-sm whitespace-nowrap outline-none transition-colors focus-visible:ring-3 focus-visible:ring-ring/50',
              active === option.name ? 'bg-muted font-medium text-foreground' : 'text-muted-foreground hover:bg-muted/60 hover:text-foreground',
            )}
          >
            <option.icon className="size-4 shrink-0" aria-hidden="true" />
            <span className="flex-1 truncate">{option.label}</span>
            <span className="text-xs tabular-nums">{option.count}</span>
          </button>
        </li>
      ))}
    </ul>
  )
}

export default function Tools({ agent, onNext, onBack }) {
  const catalog = useToolCatalog()
  const setTools = useSetAgentTools()
  const [selected, setSelected] = useState(() => new Set(agent.tools))
  const [query, setQuery] = useState('')
  const [category, setCategory] = useState(null) // null shows every category
  const [onlySelected, setOnlySelected] = useState(false)

  if (catalog.isPending) {
    return (
      <div className="flex flex-col gap-4" role="status" aria-label="Loading tools">
        <Skeleton className="h-7 w-72" />
        <Skeleton className="h-9" />
        <div className="grid gap-3 sm:grid-cols-2">
          {Array.from({ length: 6 }, (_, i) => (
            <Skeleton key={i} className="h-24" />
          ))}
        </div>
      </div>
    )
  }
  if (catalog.isError) {
    return (
      <div className="flex flex-col items-start gap-3 rounded-xl border p-6">
        <p className="text-sm text-destructive">The tools couldn&apos;t load.</p>
        <Button variant="outline" onClick={() => catalog.refetch()}>
          Retry
        </Button>
      </div>
    )
  }

  function toggle(names, on) {
    setSelected((current) => {
      const next = new Set(current)
      for (const name of names) {
        if (on) next.add(name)
        else next.delete(name)
      }
      return next
    })
  }

  function onSubmit(event) {
    event.preventDefault()
    setTools.mutate({ id: agent.id, tools: [...selected] }, { onSuccess: onNext })
  }

  const apps = toApps(catalog.data.groups)
  const categories = catalog.data.groups.map((group) => group.name)
  const isOn = (app) => app.tools.some((tool) => selected.has(tool.name))
  const shown = apps.filter(
    (app) => (!category || app.category === category) && matches(app, query) && (!onlySelected || isOn(app)),
  )
  const selectedApps = apps.filter(isOn).length

  return (
    <form onSubmit={onSubmit} className="flex flex-col gap-5">
      <div>
        <h2 className="text-lg font-semibold">Select your tools and API access</h2>
        <p className="mt-1 text-sm text-muted-foreground">
          Switch on the services your agent may use. It calls one only when a question needs it.
        </p>
      </div>

      <div className="flex flex-wrap items-center gap-3">
        <div className="flex rounded-lg border p-0.5" role="group" aria-label="Which services to show">
          {[
            { value: false, label: 'All', count: apps.length },
            { value: true, label: 'Selected', count: selectedApps },
          ].map((tab) => (
            <button
              key={tab.label}
              type="button"
              aria-pressed={onlySelected === tab.value}
              onClick={() => setOnlySelected(tab.value)}
              className={cn(
                'flex cursor-pointer items-center gap-2 rounded-md px-3 py-1.5 text-sm outline-none transition-colors focus-visible:ring-3 focus-visible:ring-ring/50',
                onlySelected === tab.value ? 'bg-primary/10 font-medium text-primary' : 'text-muted-foreground hover:text-foreground',
              )}
            >
              {tab.label}
              <span className="rounded bg-muted px-1.5 text-xs tabular-nums text-muted-foreground">{tab.count}</span>
            </button>
          ))}
        </div>
        <div className="relative min-w-48 flex-1">
          <Search className="pointer-events-none absolute top-1/2 left-2.5 size-4 -translate-y-1/2 text-muted-foreground" aria-hidden="true" />
          <Input
            type="search"
            value={query}
            onChange={(event) => setQuery(event.target.value)}
            placeholder="Search services and tools"
            aria-label="Search services and tools"
            className="pl-8"
          />
        </div>
      </div>

      {/* Small screens: categories as a scrolling row above the cards. */}
      <CategoryList
        categories={categories}
        apps={apps}
        active={category}
        onPick={setCategory}
        className="flex gap-1 overflow-x-auto lg:hidden"
      />

      <div className="flex items-start gap-6">
        <div className="flex min-w-0 flex-1 flex-col gap-7">
          {shown.length === 0 ? (
            <div className="flex flex-col items-center gap-3 rounded-xl border border-dashed p-10 text-center">
              <p className="text-sm text-muted-foreground">
                {onlySelected && !query && !category ? 'No services are switched on yet.' : 'No services match.'}
              </p>
              <Button
                type="button"
                variant="outline"
                onClick={() => {
                  setQuery('')
                  setCategory(null)
                  setOnlySelected(false)
                }}
              >
                Show all services
              </Button>
            </div>
          ) : (
            categories
              .filter((name) => shown.some((app) => app.category === name))
              .map((name) => (
                <section key={name} aria-labelledby={`category-${name}`} className="flex flex-col gap-3">
                  <h3 id={`category-${name}`} className="text-base font-semibold">
                    {name}
                  </h3>
                  <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-3">
                    {shown
                      .filter((app) => app.category === name)
                      .map((app) => (
                        <AppCard key={`${app.category}-${app.name}`} app={app} selected={selected} onToggle={toggle} />
                      ))}
                  </div>
                </section>
              ))
          )}
        </div>

        <aside className="sticky top-4 hidden w-64 shrink-0 rounded-md border lg:block" aria-label="Categories">
          <p className="border-b px-4 py-3 text-sm font-semibold">Categories</p>
          <CategoryList
            categories={categories}
            apps={apps}
            active={category}
            onPick={setCategory}
            className="flex flex-col gap-0.5 p-2"
          />
        </aside>
      </div>

      <StepFooter onBack={onBack} saving={setTools.isPending} error={setTools.error?.message} />
    </form>
  )
}
