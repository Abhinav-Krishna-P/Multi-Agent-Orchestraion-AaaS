import { Component } from 'react'
import { Images, Links, Places, Products, Stays, Symbols } from './lists'
import { Calculation, Clock, Conversion, Flights, Forecast, Quote, Rates, Translation, Weather } from './panels'

const KINDS = {
  products: Products,
  stays: Stays,
  links: Links,
  images: Images,
  places: Places,
  symbols: Symbols,
  flights: Flights,
  weather: Weather,
  forecast: Forecast,
  conversion: Conversion,
  rates: Rates,
  quote: Quote,
  translation: Translation,
  calculation: Calculation,
  clock: Clock,
}

/**
 * Cards are drawn from whatever a service sent. If one field has an unexpected shape, only
 * that card is dropped: without this the whole chat would go blank, and stay blank each time
 * it is reopened, because the card is saved with the message.
 */
class CardBoundary extends Component {
  state = { failed: false }

  static getDerivedStateFromError() {
    return { failed: true }
  }

  render() {
    return this.state.failed ? null : this.props.children
  }
}

/** The results of the tools a reply used, drawn as cards. A kind this page doesn't know shows nothing. */
export function ResultCards({ tools }) {
  const cards = (tools ?? []).filter((tool) => tool.card && KINDS[tool.card.kind])
  if (cards.length === 0) return null
  return (
    <div className="mt-3 flex flex-col gap-3">
      {cards.map((tool, index) => {
        const Card = KINDS[tool.card.kind]
        return (
          // Keyed by position: it is the same while a reply streams and after it is saved.
          <CardBoundary key={index}>
            <Card card={tool.card} />
          </CardBoundary>
        )
      })}
    </div>
  )
}
