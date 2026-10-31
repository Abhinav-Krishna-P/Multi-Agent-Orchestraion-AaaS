import { BedDouble, ChevronLeft, ChevronRight, Globe, Image as ImageIcon, MapPin, Phone, ShoppingBag } from 'lucide-react'
import { useState } from 'react'
import { safeUrl } from './format'
import { Action, CardImage, ExtLink, Frame, Stars } from './shared'

// relative: screen-reader-only text inside a tile is absolutely positioned; this keeps it inside
// the row's own scroll area instead of widening the whole page.
const ROW = 'relative flex snap-x gap-3 overflow-x-auto p-4'
const TILE = 'flex shrink-0 snap-start flex-col overflow-hidden rounded-lg border bg-background'

function Badge({ children }) {
  return <span className="shrink-0 rounded bg-muted px-1.5 py-0.5 text-[11px] font-medium whitespace-nowrap text-muted-foreground">{children}</span>
}

/** Amazon and Google Shopping: a row of product tiles; a whole tile opens the product. */
export function Products({ card }) {
  return (
    <Frame service={card.service} heading={`${card.items.length} products`}>
      <ul className={ROW}>
        {card.items.map((item, index) => (
          <li key={index} className="w-44 shrink-0 snap-start">
            <ExtLink
              href={item.link}
              className={`${TILE} h-full outline-none transition-shadow hover:shadow-md focus-visible:ring-3 focus-visible:ring-ring/50`}
            >
              <div className="relative flex h-40 shrink-0 items-center justify-center bg-white p-3">
                <CardImage
                  src={item.image}
                  className="size-full object-contain"
                  fallback={<ShoppingBag className="size-8 text-muted-foreground/50" aria-hidden="true" />}
                />
                {item.sponsored && (
                  <span className="absolute top-1.5 left-1.5">
                    <Badge>Sponsored</Badge>
                  </span>
                )}
              </div>
              <div className="flex flex-1 flex-col gap-1.5 border-t p-3">
                <p className="line-clamp-2 text-xs font-medium" title={item.title}>
                  {item.title}
                </p>
                {item.price && (
                  <p className="flex flex-wrap items-baseline gap-x-1.5">
                    <span className="text-sm font-semibold">{item.price}</span>
                    {item.old_price && <s className="text-xs text-muted-foreground">{item.old_price}</s>}
                    {item.price_unit && <span className="text-[11px] text-muted-foreground">({item.price_unit})</span>}
                  </p>
                )}
                <Stars rating={item.rating} reviews={item.reviews} />
                {item.store && <p className="truncate text-xs text-muted-foreground">{item.store}</p>}
                {item.bought_last_month && <p className="text-[11px] text-muted-foreground">{item.bought_last_month}</p>}
                {item.delivery?.[0] && <p className="line-clamp-2 text-[11px] text-green-700">{item.delivery.join(' · ')}</p>}
                {item.offers?.[0] && <p className="line-clamp-2 text-[11px] text-muted-foreground">{item.offers[0]}</p>}
                {safeUrl(item.link) && <span className="mt-auto pt-1 text-xs font-medium text-primary">View ↗</span>}
              </div>
            </ExtLink>
          </li>
        ))}
      </ul>
    </Frame>
  )
}

function Photos({ images, alt }) {
  const [index, setIndex] = useState(0)
  const count = images?.length ?? 0
  const step = (by) => setIndex((current) => (current + by + count) % count)
  return (
    <div className="relative aspect-[4/3] shrink-0 overflow-hidden bg-muted">
      <CardImage
        key={index}
        src={images?.[index]}
        alt={alt}
        // Absolute, so a tall photo is cropped to the frame instead of stretching the tile.
        className="absolute inset-0 size-full object-cover"
        fallback={
          <div className="flex size-full items-center justify-center">
            <BedDouble className="size-8 text-muted-foreground/50" aria-hidden="true" />
          </div>
        }
      />
      {count > 1 && (
        <>
          {[
            { by: -1, label: 'Previous photo', Icon: ChevronLeft, side: 'left-1.5' },
            { by: 1, label: 'Next photo', Icon: ChevronRight, side: 'right-1.5' },
          ].map(({ by, label, Icon, side }) => (
            <button
              key={label}
              type="button"
              aria-label={label}
              onClick={() => step(by)}
              className={`absolute top-1/2 ${side} flex size-7 -translate-y-1/2 cursor-pointer items-center justify-center rounded-full bg-background/90 shadow outline-none hover:bg-background focus-visible:ring-3 focus-visible:ring-ring/50`}
            >
              <Icon className="size-4" aria-hidden="true" />
            </button>
          ))}
          <span className="absolute right-1.5 bottom-1.5 rounded bg-black/60 px-1.5 py-0.5 text-[11px] text-white">
            {index + 1} / {count}
          </span>
        </>
      )}
    </div>
  )
}

const plural = (count, word) => (count == null ? null : `${count} ${word}${count === 1 ? '' : 's'}`)

/** Airbnb: a row of stays, each with its photos to flick through. */
export function Stays({ card }) {
  return (
    <Frame service={card.service} heading={`${card.items.length} stays`}>
      <ul className={ROW}>
        {card.items.map((item, index) => {
          const map =
            item.latitude != null && item.longitude != null
              ? `https://www.google.com/maps?q=${item.latitude},${item.longitude}`
              : undefined
          return (
            <li key={index} className={`${TILE} w-64`}>
              <Photos images={item.images} alt={item.name ?? item.title ?? ''} />
              <div className="flex flex-1 flex-col gap-1.5 p-3">
                <div className="flex items-start justify-between gap-2">
                  <p className="line-clamp-1 text-sm font-semibold" title={item.name ?? item.title}>
                    {item.name ?? item.title}
                  </p>
                  {item.rating != null ? <Stars rating={item.rating} reviews={item.reviews} /> : item.is_new && <Badge>New</Badge>}
                </div>
                {item.name && item.title && <p className="truncate text-xs text-muted-foreground">{item.title}</p>}
                {item.description && <p className="line-clamp-2 text-xs text-muted-foreground">{item.description}</p>}
                <p className="text-xs text-muted-foreground">
                  {[plural(item.bedrooms, 'bedroom'), plural(item.beds, 'bed'), plural(item.bathrooms, 'bath')]
                    .filter(Boolean)
                    .join(' · ')}
                </p>
                {item.price && (
                  <p className="flex flex-wrap items-baseline gap-x-1.5 pt-1">
                    <span className="text-sm font-semibold">{item.price}</span>
                    {item.old_price && <s className="text-xs text-muted-foreground">{item.old_price}</s>}
                    {item.price_qualifier && <span className="text-xs text-muted-foreground">{item.price_qualifier}</span>}
                  </p>
                )}
                <div className="mt-auto flex items-center gap-4 pt-1.5">
                  <Action href={item.link}>View on Airbnb</Action>
                  <Action href={map}>Map</Action>
                </div>
              </div>
            </li>
          )
        })}
      </ul>
    </Frame>
  )
}

/** Web results, news and books: stacked rows with a thumbnail when the service sent one. */
export function Links({ card }) {
  return (
    <Frame service={card.service} heading={`${card.items.length} results`}>
      {card.answer && <p className="border-b bg-primary/5 px-4 py-3 text-sm font-medium">{card.answer}</p>}
      <ul className="divide-y">
        {card.items.map((item, index) => (
          <li key={index} className="flex gap-3 px-4 py-3">
            <CardImage src={item.image} className="size-16 shrink-0 rounded-md bg-muted object-cover" />
            <div className="min-w-0 flex-1">
              <p className="flex items-center gap-1.5 text-xs text-muted-foreground">
                <CardImage src={item.favicon} className="size-3.5 shrink-0 rounded-sm" />
                <span className="truncate">
                  {[item.source, item.authors?.join(', '), item.date].filter(Boolean).join(' · ')}
                </span>
              </p>
              <ExtLink
                href={item.link}
                className="line-clamp-2 rounded-sm text-sm font-medium text-primary outline-none hover:underline focus-visible:ring-3 focus-visible:ring-ring/50"
              >
                {item.title}
              </ExtLink>
              {item.snippet && <p className="mt-0.5 line-clamp-2 text-xs text-muted-foreground">{item.snippet}</p>}
            </div>
          </li>
        ))}
      </ul>
    </Frame>
  )
}

/** Image search: a grid of pictures; each opens the page it is on. */
export function Images({ card }) {
  return (
    <Frame service={card.service} heading={`${card.items.length} images`}>
      <ul className="grid grid-cols-2 gap-2 p-4 sm:grid-cols-4">
        {card.items.map((item, index) => (
          <li key={index}>
            <ExtLink
              href={item.link ?? item.image}
              title={item.title}
              className="group relative block aspect-square overflow-hidden rounded-lg bg-muted outline-none focus-visible:ring-3 focus-visible:ring-ring/50"
            >
              <CardImage
                src={item.thumbnail ?? item.image}
                alt={item.title ?? ''}
                className="absolute inset-0 size-full object-cover transition-transform group-hover:scale-105"
                fallback={
                  <span className="flex size-full items-center justify-center">
                    <ImageIcon className="size-6 text-muted-foreground/50" aria-hidden="true" />
                  </span>
                }
              />
              {item.source && (
                <span className="absolute inset-x-0 bottom-0 truncate bg-black/60 px-2 py-1 text-[11px] text-white">
                  {item.source}
                </span>
              )}
            </ExtLink>
          </li>
        ))}
      </ul>
    </Frame>
  )
}

/** Places: one row each, with ways to act on it (map, website, call). */
export function Places({ card }) {
  return (
    <Frame service={card.service} heading={`${card.items.length} places`}>
      <ul className="divide-y">
        {card.items.map((item, index) => (
          <li key={index} className="flex gap-3 px-4 py-3">
            <span className="flex size-9 shrink-0 items-center justify-center rounded-md bg-primary/10">
              <MapPin className="size-4 text-primary" aria-hidden="true" />
            </span>
            <div className="min-w-0 flex-1">
              <div className="flex flex-wrap items-center gap-x-2 gap-y-0.5">
                <p className="text-sm font-semibold">{item.name}</p>
                <Stars rating={item.rating} reviews={item.reviews} />
              </div>
              <p className="text-xs text-muted-foreground">
                {[item.category, item.price_level, item.address].filter(Boolean).join(' · ')}
              </p>
              <div className="mt-1.5 flex flex-wrap items-center gap-x-4 gap-y-1">
                <Action href={item.link}>Open in Maps</Action>
                {safeUrl(item.website) && (
                  <Action href={item.website}>
                    <Globe className="size-3" aria-hidden="true" /> Website
                  </Action>
                )}
                {item.phone && (
                  // Built from the digits only, so the service's text can't become any other kind of link.
                  <a
                    href={`tel:${String(item.phone).replace(/[^\d+]/g, '')}`}
                    className="inline-flex items-center gap-1 rounded-sm text-xs font-medium text-primary outline-none hover:underline focus-visible:ring-3 focus-visible:ring-ring/50"
                  >
                    <Phone className="size-3" aria-hidden="true" /> {item.phone}
                  </a>
                )}
              </div>
            </div>
          </li>
        ))}
      </ul>
    </Frame>
  )
}

/** Stock symbols that matched a company name. */
export function Symbols({ card }) {
  return (
    <Frame service={card.service} heading={`${card.items.length} matches`}>
      <ul className="divide-y">
        {card.items.map((item, index) => (
          <li key={index} className="flex items-center gap-3 px-4 py-2.5 text-sm">
            <span className="w-24 shrink-0 font-mono font-semibold">{item.symbol}</span>
            <span className="min-w-0 flex-1 truncate">{item.name}</span>
            {item.type && <span className="shrink-0 text-xs text-muted-foreground">{item.type}</span>}
          </li>
        ))}
      </ul>
    </Frame>
  )
}
