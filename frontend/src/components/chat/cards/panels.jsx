import {
  ArrowRight,
  Cloud,
  CloudDrizzle,
  CloudFog,
  CloudLightning,
  CloudRain,
  CloudSnow,
  CloudSun,
  Droplets,
  Leaf,
  Moon,
  Plane,
  Sun,
  Sunrise,
  Sunset,
  Thermometer,
  TrendingDown,
  TrendingUp,
  Umbrella,
  Wind,
} from 'lucide-react'
import { cn } from '@/lib/utils'
import { money, number } from './format'
import { CardImage, CopyButton, Fact, Frame } from './shared'

const duration = (minutes) =>
  typeof minutes === 'number' ? [Math.floor(minutes / 60) && `${Math.floor(minutes / 60)} h`, minutes % 60 && `${minutes % 60} min`].filter(Boolean).join(' ') : null
const clock = (time) => (typeof time === 'string' ? time.slice(-5) : '')
const day = (date, options = { weekday: 'short', day: 'numeric', month: 'short' }) => {
  const parsed = new Date(`${String(date).slice(0, 10)}T00:00`)
  return Number.isNaN(parsed.getTime()) ? date : parsed.toLocaleDateString(undefined, options)
}

function Flight({ flight, currency }) {
  const first = flight.legs[0]
  const last = flight.legs[flight.legs.length - 1]
  const airlines = [...new Set(flight.legs.map((leg) => leg.airline).filter(Boolean))].join(', ')
  const nextDay = first && last && first.from?.time?.slice(0, 10) !== last.to?.time?.slice(0, 10)
  return (
    <li className="px-4 py-3">
      <div className="flex items-center gap-3">
        <CardImage
          src={flight.logo ?? first?.logo}
          className="size-8 shrink-0 object-contain"
          fallback={<Plane className="size-6 shrink-0 text-muted-foreground" aria-hidden="true" />}
        />
        <div className="min-w-0 flex-1">
          {first ? (
            <p className="flex flex-wrap items-center gap-x-2 text-sm font-semibold">
              <span>
                {clock(first.from?.time)} <span className="font-normal text-muted-foreground">{first.from?.id}</span>
              </span>
              <ArrowRight className="size-3.5 text-muted-foreground" aria-hidden="true" />
              <span>
                {clock(last.to?.time)} <span className="font-normal text-muted-foreground">{last.to?.id}</span>
                {nextDay && <sup className="ml-0.5 text-[10px] font-normal text-muted-foreground">next day</sup>}
              </span>
            </p>
          ) : (
            <p className="text-sm font-semibold">{flight.title}</p>
          )}
          <p className="truncate text-xs text-muted-foreground">
            {[
              airlines,
              duration(flight.duration_minutes),
              flight.stops === 0 ? 'Nonstop' : `${flight.stops} stop${flight.stops === 1 ? '' : 's'}`,
              flight.trip,
            ]
              .filter(Boolean)
              .join(' · ')}
          </p>
        </div>
        <div className="shrink-0 text-right">
          {flight.price != null && <p className="text-sm font-semibold">{money(flight.price, currency)}</p>}
          {flight.emissions_percent != null && (
            <p className={cn('flex items-center justify-end gap-1 text-[11px]', flight.emissions_percent <= 0 ? 'text-green-700' : 'text-muted-foreground')}>
              <Leaf className="size-3" aria-hidden="true" />
              {flight.emissions_percent > 0 && '+'}
              {flight.emissions_percent}% CO₂
            </p>
          )}
        </div>
      </div>
      {flight.legs.length > 0 && (
        <details className="mt-2 text-xs">
          <summary className="w-fit cursor-pointer rounded-sm text-muted-foreground outline-none hover:text-foreground focus-visible:ring-3 focus-visible:ring-ring/50">
            Flight details
          </summary>
          <ol className="mt-2 flex flex-col gap-2 border-l-2 pl-3">
            {flight.legs.map((leg, index) => (
              <li key={index}>
                <p className="font-medium">
                  {[leg.airline, leg.flight].filter(Boolean).join(' ')} · {leg.from?.id} {clock(leg.from?.time)} → {leg.to?.id}{' '}
                  {clock(leg.to?.time)}
                </p>
                <p className="text-muted-foreground">
                  {leg.from?.name} to {leg.to?.name}
                </p>
                <p className="text-muted-foreground">
                  {[
                    day(leg.from?.time),
                    duration(leg.duration),
                    leg.airplane,
                    leg.travel_class,
                    leg.legroom && `${leg.legroom} legroom`,
                    leg.overnight && 'Overnight',
                    leg.often_delayed && 'Often delayed 30+ min',
                  ]
                    .filter(Boolean)
                    .join(' · ')}
                </p>
                {flight.layovers[index] && (
                  <p className="mt-2 text-amber-700">
                    Layover: {[duration(flight.layovers[index].duration), flight.layovers[index].name, flight.layovers[index].overnight && 'overnight'].filter(Boolean).join(' · ')}
                  </p>
                )}
              </li>
            ))}
          </ol>
        </details>
      )}
    </li>
  )
}

export function Flights({ card }) {
  const route = `${card.origin ?? card.origin_code} (${card.origin_code}) → ${card.destination ?? card.destination_code} (${card.destination_code})`
  const range = card.typical_price_range
  return (
    <Frame service={card.service} heading={route} link={card.link} linkLabel="Open in Google Flights">
      <p className="flex flex-wrap gap-x-3 gap-y-1 border-b bg-muted/40 px-4 py-2 text-xs text-muted-foreground">
        <span>
          {day(card.date)}
          {card.return_date && ` – ${day(card.return_date)}`}
        </span>
        {card.lowest_price != null && (
          <span>
            Lowest <span className="font-medium text-foreground">{money(card.lowest_price, card.currency)}</span>
          </span>
        )}
        {card.price_level && <span>Prices are {card.price_level} now</span>}
        {range?.length === 2 && (
          <span>
            Usually {money(range[0], card.currency)} – {money(range[1], card.currency)}
          </span>
        )}
      </p>
      <ul className="divide-y">
        {card.items.map((flight, index) => (
          <Flight key={index} flight={flight} currency={card.currency} />
        ))}
      </ul>
    </Frame>
  )
}

const WEATHER_ICONS = {
  'Clear sky': Sun,
  'Partly cloudy': CloudSun,
  Overcast: Cloud,
  Fog: CloudFog,
  Drizzle: CloudDrizzle,
  Rain: CloudRain,
  'Rain showers': CloudRain,
  Snow: CloudSnow,
  'Snow showers': CloudSnow,
  Thunderstorm: CloudLightning,
}

function WeatherIcon({ conditions, night, className }) {
  const Icon = night && conditions === 'Clear sky' ? Moon : (WEATHER_ICONS[conditions] ?? Cloud)
  return <Icon className={className} aria-hidden="true" />
}

const degrees = (value) => (value == null ? null : `${Math.round(value)}°C`)

export function Weather({ card }) {
  return (
    <Frame service={card.service} heading={card.place}>
      <div className="flex flex-wrap items-center gap-x-8 gap-y-4 p-4">
        <div className="flex items-center gap-3">
          <WeatherIcon conditions={card.conditions} night={card.is_day === 0} className="size-12 text-primary" />
          <div>
            <p className="text-3xl leading-none font-semibold">{degrees(card.temperature_c)}</p>
            <p className="mt-1 text-sm text-muted-foreground">{card.conditions}</p>
          </div>
        </div>
        <dl className="grid flex-1 grid-cols-2 gap-x-6 gap-y-3 sm:grid-cols-4">
          <Fact label="Feels like" icon={Thermometer}>
            {degrees(card.feels_like_c)}
          </Fact>
          <Fact label="Humidity" icon={Droplets}>
            {card.humidity_percent != null && `${card.humidity_percent}%`}
          </Fact>
          <Fact label="Wind" icon={Wind}>
            {card.wind_kmh != null && `${card.wind_kmh} km/h`}
          </Fact>
          <Fact label="Rain now" icon={Umbrella}>
            {card.precipitation_mm != null && `${card.precipitation_mm} mm`}
          </Fact>
        </dl>
      </div>
      {card.time && (
        <p className="border-t px-4 py-2 text-xs text-muted-foreground">
          As of {day(card.time)}, {clock(card.time)} local time
        </p>
      )}
    </Frame>
  )
}

export function Forecast({ card }) {
  return (
    <Frame service={card.service} heading={`${card.place} · ${card.days.length}-day forecast`}>
      <ul className="flex snap-x gap-3 overflow-x-auto p-4">
        {card.days.map((item) => (
          <li key={item.date} className="flex w-32 shrink-0 snap-start flex-col items-center gap-1 rounded-lg border p-3 text-center">
            <p className="text-xs font-medium">{day(item.date)}</p>
            <WeatherIcon conditions={item.conditions} className="size-8 text-primary" />
            <p className="text-xs text-muted-foreground">{item.conditions}</p>
            <p className="text-sm font-semibold">
              {degrees(item.high_c)} <span className="font-normal text-muted-foreground">{degrees(item.low_c)}</span>
            </p>
            <ul className="mt-1 flex w-full flex-col gap-0.5 border-t pt-2 text-[11px] text-muted-foreground">
              {item.rain_chance_percent != null && (
                <li className="flex items-center justify-center gap-1">
                  <Umbrella className="size-3" aria-hidden="true" /> {item.rain_chance_percent}%
                  {item.rain_mm != null && ` · ${item.rain_mm} mm`}
                </li>
              )}
              {item.wind_kmh != null && (
                <li className="flex items-center justify-center gap-1">
                  <Wind className="size-3" aria-hidden="true" /> {item.wind_kmh} km/h
                </li>
              )}
              {item.uv_index != null && <li>UV {item.uv_index}</li>}
              {item.sunrise && (
                <li className="flex items-center justify-center gap-1">
                  <Sunrise className="size-3" aria-hidden="true" /> {clock(item.sunrise)}
                  {item.sunset && (
                    <>
                      <Sunset className="ml-1 size-3" aria-hidden="true" /> {clock(item.sunset)}
                    </>
                  )}
                </li>
              )}
            </ul>
          </li>
        ))}
      </ul>
    </Frame>
  )
}

export function Conversion({ card }) {
  return (
    <Frame service={card.service} heading="Currency conversion">
      <div className="flex flex-wrap items-end justify-between gap-3 p-4">
        <div>
          <p className="text-sm text-muted-foreground">
            {number(card.amount)} {card.from} =
          </p>
          <p className="text-3xl font-semibold">
            {number(card.result, { maximumFractionDigits: 2 })} <span className="text-lg text-muted-foreground">{card.to}</span>
          </p>
          <p className="mt-1 text-xs text-muted-foreground">
            1 {card.from} = {number(card.rate, { maximumFractionDigits: 6 })} {card.to}
          </p>
        </div>
        <CopyButton text={card.result} />
      </div>
    </Frame>
  )
}

export function Rates({ card }) {
  return (
    <Frame service={card.service} heading={`1 ${card.base} equals`}>
      <dl className="grid grid-cols-2 gap-x-6 gap-y-3 p-4 sm:grid-cols-4">
        {Object.entries(card.rates).map(([code, rate]) => (
          <Fact key={code} label={code}>
            {number(rate, { maximumFractionDigits: 4 })}
          </Fact>
        ))}
      </dl>
    </Frame>
  )
}

// Finnhub gives the market value in millions.
const marketCap = (millions) =>
  typeof millions !== 'number'
    ? null
    : millions >= 1e6
      ? `${(millions / 1e6).toFixed(2)} T`
      : millions >= 1e3
        ? `${(millions / 1e3).toFixed(2)} B`
        : `${millions.toFixed(0)} M`

export function Quote({ card }) {
  const up = (card.change ?? 0) >= 0
  const Trend = up ? TrendingUp : TrendingDown
  const price = (value) => (value == null ? null : card.currency ? money(value, card.currency) : number(value))
  return (
    <Frame service={card.service} heading={card.exchange} link={card.website} linkLabel="Company site">
      <div className="flex flex-wrap items-center gap-x-8 gap-y-4 p-4">
        <div className="flex items-center gap-3">
          <CardImage src={card.logo} className="size-10 shrink-0 rounded-md object-contain" />
          <div>
            <p className="text-sm font-medium">
              {card.name ?? card.symbol} {card.name && <span className="font-mono text-xs text-muted-foreground">{card.symbol}</span>}
            </p>
            <p className="text-3xl leading-tight font-semibold">{price(card.price)}</p>
            {card.change != null && (
              <p className={cn('flex items-center gap-1 text-sm font-medium', up ? 'text-green-700' : 'text-destructive')}>
                <Trend className="size-4" aria-hidden="true" />
                {up && '+'}
                {number(card.change, { maximumFractionDigits: 2 })}
                {card.change_percent != null && ` (${up ? '+' : ''}${number(card.change_percent, { maximumFractionDigits: 2 })}%)`}
                <span className="sr-only">{up ? 'up' : 'down'} today</span>
              </p>
            )}
          </div>
        </div>
        <dl className="grid flex-1 grid-cols-2 gap-x-6 gap-y-3 sm:grid-cols-3">
          <Fact label="Open">{price(card.open)}</Fact>
          <Fact label="High">{price(card.high)}</Fact>
          <Fact label="Low">{price(card.low)}</Fact>
          <Fact label="Previous close">{price(card.previous_close)}</Fact>
          <Fact label="Market value">{marketCap(card.market_cap_millions)}</Fact>
          <Fact label="Industry">{card.industry}</Fact>
        </dl>
      </div>
      {card.time > 0 && (
        <p className="border-t px-4 py-2 text-xs text-muted-foreground">As of {new Date(card.time * 1000).toLocaleString()}</p>
      )}
    </Frame>
  )
}

export function Translation({ card }) {
  return (
    <Frame service={card.service} heading={`${card.from} → ${card.to}`} link={card.link} linkLabel="Open in Google Translate">
      <div className="grid gap-4 p-4 sm:grid-cols-2">
        <div>
          <p className="text-xs text-muted-foreground">{card.from}</p>
          <p className="mt-1 text-sm whitespace-pre-wrap">{card.text}</p>
          {card.source_pronunciation && <p className="mt-1 text-xs text-muted-foreground">{card.source_pronunciation}</p>}
        </div>
        <div className="sm:border-l sm:pl-4">
          <p className="text-xs text-muted-foreground">{card.to}</p>
          <p className="mt-1 text-lg font-medium whitespace-pre-wrap">{card.translation}</p>
          {card.pronunciation && <p className="mt-1 text-xs text-muted-foreground">{card.pronunciation}</p>}
          <div className="mt-3">
            <CopyButton text={card.translation} />
          </div>
        </div>
      </div>
    </Frame>
  )
}

export function Calculation({ card }) {
  return (
    <Frame service={card.service}>
      <div className="flex flex-wrap items-end justify-between gap-3 p-4">
        <div className="min-w-0">
          <p className="font-mono text-sm break-all text-muted-foreground">{card.expression} =</p>
          <p className="font-mono text-3xl font-semibold break-all">{card.result}</p>
        </div>
        <CopyButton text={card.result} />
      </div>
    </Frame>
  )
}

export function Clock({ card }) {
  return (
    <Frame service={card.service} heading={card.timezone}>
      <div className="p-4">
        <p className="text-3xl font-semibold tabular-nums">{card.time}</p>
        <p className="mt-1 text-sm">
          {card.weekday}, {card.date}
        </p>
        <p className="text-xs text-muted-foreground">{card.offset}</p>
      </div>
    </Frame>
  )
}
