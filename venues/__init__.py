"""Venue-agnostic cross-venue layer for `market_maker/` (ARCHITECTURE.md §7,
next_steps.md #6/#11): a shared `OfferBookReader` interface plus one
implementation per connected venue. `basicswap/` remains its own,
BasicSwap-specific venue module (own strategy, own live capital) — this
package is read-only observation only, no wallet, no capital, no order
placement anywhere.
"""
