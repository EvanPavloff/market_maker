"""Thin, read-only client for BasicSwap's local JSON API — served on the same port
as the web UI itself (localhost:12700, not 12701 as doc/api.md's curl examples
claim; verified live 2026-09-15, see ARCHITECTURE.md §5).

Uses only the stdlib (urllib) — this workspace's convention is to avoid a new pip
dependency when one isn't earned (see world_tracker's dependency-free xlsx reader for
the same call). BasicSwap's own venv doesn't have `requests` installed either.

Phase 1 read-only routes (ARCHITECTURE.md §5/§6):
  - POST /json/offers     — live order book (both own and others' offers)
  - GET  /json/rateslist  — external reference rate BasicSwap itself looks up.
    Not /json/rates (POST) — that route passes coin_from/coin_to straight into
    lookupRates() without the getCoinType() ticker->int conversion js_rates_list
    does, so it 500s on string tickers like "xmr" (found live 2026-09-15).

Write routes (real offers, real BTC/XMR) — added 2026-09-17 with Evan's explicit
go-ahead for a live market-making test, per the sign-off this docstring used to
say was still needed:
  - POST /json/offers/new   — post_offer(). Field names/units match exactly what
    BasicSwap's own web form sends (ui/page_offers.py's parseOfferFormData) —
    decimal-string amounts/rate, not integer coin units; that conversion happens
    server-side.
  - POST /json/revokeoffer/<id> — revoke_offer().
  - POST /json/offers (sent=True query) via get_sent_offers() — read-only, but
    kept next to the write methods since it's how a caller finds its own live
    offer to revoke/reprice.

post_offer() always passes automation_strat_id (default "1" = BasicSwap's own
built-in "Accept All" strategy) explicitly — confirmed live 2026-09-17 that this
strategy already has exact_rate_only=True and max_concurrent_bids=1 baked in
(db_upgrades.py's seed data), so no custom strategy needed. Leaving
automation_strat_id unset entirely means NO automation link gets created at all
(postNewOfferFromParsed only wires one up if a strategy id was explicitly given —
there's no separate auto_accept_bids form flag), i.e. bids would need manual
acceptance — pass automation_strat_id=None deliberately if that's what's wanted.

Bid-side write routes (opportunistic bid-scanning, next_steps.md #9, added
2026-09-20 at Evan's explicit go-ahead) — bidding into OTHER makers' offers,
not posting our own:
  - POST /json/bids/new — post_bid(). Field names read directly from
    js_server.py's js_bids "new" branch: offer_id/amount_from/bid_rate, same
    decimal-string-not-float convention as post_offer(). amount_from here is
    in the OFFER's own coin_from units (how much of what the maker is selling
    we want to buy), not our own paying currency — matches
    place_bid_on_offer()'s payload in BasicSwap's own createoffers.py.
  - POST /json/bids/<bid_id> (empty body) — get_bid(). Read-only, but a write-
    adjacent route: the only way to learn a bid's real BidStates outcome
    (Completed vs. Abandoned/Failed/Timed-out/etc, describeBid()'s
    "bid_state" field) after post_bid() submits it — used by
    bid_scanner.reconcile_bid_outcomes() to audit whether a submitted bid
    actually turned into a completed swap, independent of anything in
    live_maker.py's own offer-side event log.
"""

import base64
import json
import urllib.error
import urllib.parse
import urllib.request
from typing import Any


class BasicSwapAPIError(RuntimeError):
    """Raised on a network failure, non-2xx response, or an {"error": ...} body."""


class BasicSwapClient:
    def __init__(
        self,
        base_url: str,
        auth_user: str | None = None,
        auth_password: str | None = None,
        timeout_seconds: float = 10.0,
    ):
        self.base_url = base_url.rstrip("/")
        self._auth_header = None
        if auth_password:
            creds = f"{auth_user or ''}:{auth_password}".encode("utf-8")
            self._auth_header = "Basic " + base64.b64encode(creds).decode("ascii")
        self.timeout_seconds = timeout_seconds

    def _request(self, req: urllib.request.Request, url: str) -> Any:
        if self._auth_header:
            req.add_header("Authorization", self._auth_header)

        try:
            with urllib.request.urlopen(req, timeout=self.timeout_seconds) as resp:
                raw = resp.read().decode("utf-8")
        except urllib.error.URLError as e:
            raise BasicSwapAPIError(f"request to {url} failed: {e}") from e
        except TimeoutError as e:
            # A timeout during urlopen() itself surfaces as urllib.error.URLError
            # (caught above), already wrapping a TimeoutError as its .reason — but
            # a timeout during resp.read() (the response headers arrived, the body
            # didn't in time) raises a bare TimeoutError straight from the socket
            # layer, past urllib entirely. Found via a real incident 2026-09-18:
            # this crashed the whole live_maker loop instead of being treated as
            # the same "one API call failed, real caller decides what to do"
            # network failure every other BasicSwapAPIError already represents.
            raise BasicSwapAPIError(f"request to {url} timed out: {e}") from e

        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError as e:
            raise BasicSwapAPIError(f"non-JSON response from {url}: {raw[:200]!r}") from e

        if isinstance(parsed, dict) and "error" in parsed:
            raise BasicSwapAPIError(f"{url} returned error: {parsed['error']}")
        return parsed

    def _post(self, path: str, payload: dict[str, Any]) -> Any:
        url = f"{self.base_url}{path}"
        body = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(
            url,
            data=body,
            method="POST",
            headers={"Content-Type": "application/json"},
        )
        return self._request(req, url)

    def _get(self, path: str, query: dict[str, str]) -> Any:
        url = f"{self.base_url}{path}?{urllib.parse.urlencode(query)}"
        req = urllib.request.Request(url, method="GET")
        return self._request(req, url)

    def get_offers(
        self,
        coin_from: str | None = None,
        coin_to: str | None = None,
        include_sent: bool = True,
        limit: int = 1000,
    ) -> list[dict]:
        """Live order book. Each offer is unidirectional (coin_from -> coin_to at
        `rate`); a market's two-sided spread is the pair of opposite-direction
        offers on the same (coin_from, coin_to)/(coin_to, coin_from) pair — see
        analysis.py.
        """
        payload: dict[str, Any] = {"include_sent": include_sent, "limit": limit}
        if coin_from is not None:
            payload["coin_from"] = coin_from
        if coin_to is not None:
            payload["coin_to"] = coin_to
        offers = self._post("/json/offers", payload)
        if not isinstance(offers, list):
            raise BasicSwapAPIError(f"expected a list from /json/offers, got {type(offers)}")
        return offers

    def get_wallet_balance(self, coin: str) -> float:
        """Read-only spendable balance for one coin (/json/wallets, keyed by
        uppercase ticker — verified live 2026-09-17: {"BTC": {...}, "XMR": {...},
        "PART": {...}}). Added alongside the write methods below specifically so
        live_maker.py can check real funds are available before posting an offer
        it can't actually back — BasicSwap itself doesn't check this at offer-post
        time (validateOfferAmounts only checks chain min/max bounds, not wallet
        balance), so an unfunded offer would otherwise post successfully and only
        fail later, when a real bid tries to fund the lock transaction.
        """
        wallets = self._post("/json/wallets", {})
        if not isinstance(wallets, dict) or coin.upper() not in wallets:
            raise BasicSwapAPIError(f"no wallet info for {coin!r} in /json/wallets response")
        entry = wallets[coin.upper()]
        if not isinstance(entry, dict) or "balance" not in entry:
            # Real incident 2026-09-19: BasicSwap returned a wallet entry for a
            # coin with no "balance" key at all (transient — a retry moments
            # later had it), and the bare KeyError this used to raise wasn't
            # wrapped as BasicSwapAPIError, so it crashed the whole live_maker
            # loop the same way the 2026-09-18 TimeoutError bug did.
            raise BasicSwapAPIError(
                f"/json/wallets response for {coin!r} has no 'balance' field: {entry!r}"
            )
        return float(entry["balance"])

    def get_wallets(self) -> dict:
        """Every coin's /json/wallets entry, keyed by uppercase ticker."""
        wallets = self._post("/json/wallets", {})
        if not isinstance(wallets, dict):
            raise BasicSwapAPIError(f"unexpected response from /json/wallets: {wallets!r}")
        return wallets

    def get_wallet(self, coin: str) -> dict:
        """One coin's full /json/wallets entry: balance, unconfirmed,
        deposit_address, and (XMR) main_address — BasicSwap v0.18.8
        getWalletInfo."""
        wallets = self._post("/json/wallets", {})
        entry = wallets.get(coin.upper()) if isinstance(wallets, dict) else None
        if not isinstance(entry, dict) or "balance" not in entry:
            raise BasicSwapAPIError(f"no usable wallet info for {coin!r} in /json/wallets: {entry!r}")
        return entry

    def withdraw(self, coin: str, address: str, value: str) -> str:
        """Sends `value` (decimal string, human units) of a non-XMR coin to an
        external `address`, network fee paid on top (subfee=false). IRREVERSIBLE:
        funds leave the node's wallet. Only exolix_restock.py calls this. Returns
        the txid."""
        rv = self._post(f"/json/wallets/{coin.lower()}/withdraw",
                        {"address": address, "value": value, "subfee": False})
        if not isinstance(rv, dict) or not rv.get("txid"):
            raise BasicSwapAPIError(f"unexpected response from withdraw: {rv!r}")
        return rv["txid"]

    def get_sent_offers(
        self, coin_from: str | None = None, coin_to: str | None = None, limit: int = 100
    ) -> list[dict]:
        """This node's own live offers only (/json/sentoffers) — how a caller finds
        its current offer to compare/revoke, without filtering the full order book
        for is_own_offer itself."""
        payload: dict[str, Any] = {"limit": limit}
        if coin_from is not None:
            payload["coin_from"] = coin_from
        if coin_to is not None:
            payload["coin_to"] = coin_to
        offers = self._post("/json/sentoffers", payload)
        if not isinstance(offers, list):
            raise BasicSwapAPIError(f"expected a list from /json/sentoffers, got {type(offers)}")
        return offers

    def post_offer(
        self,
        coin_from: str,
        coin_to: str,
        amount_from: str,
        rate: str,
        lock_hours: float = 24,
        valid_hours: float = 6,
        automation_strat_id: int | None = 1,
        min_bid_amount: str | None = None,
    ) -> str:
        """Posts a real, live offer selling `amount_from` of coin_from for
        coin_to at `rate` (coin_to per coin_from, matching analysis.py's
        convention). amount_from/rate are decimal strings — BasicSwap's own
        form parser (parseOfferFormData) expects human units, not integer coin
        units; passing a plain str avoids any float-repr surprise on values
        that move real funds. `automation_strat_id=1` (default) uses
        BasicSwap's own built-in "Accept All" strategy (exact_rate_only=True,
        max_concurrent_bids=1, confirmed live 2026-09-17) — pass None for a
        manual-accept-only offer. `min_bid_amount` (coin_from units, decimal
        string, <= amount_from) is the smallest partial fill BasicSwap will
        accept — v0.18.8's parseOfferFormData reads it as `amt_bid_min`.

        Returns the new offer's id (hex string).
        """
        payload: dict[str, Any] = {
            "coin_from": coin_from,
            "coin_to": coin_to,
            "amt_from": amount_from,
            "rate": rate,
            "lockhrs": str(lock_hours),
            "validhrs": str(valid_hours),
        }
        if automation_strat_id is not None:
            payload["automation_strat_id"] = str(automation_strat_id)
        if min_bid_amount is not None:
            payload["amt_bid_min"] = min_bid_amount
        rv = self._post("/json/offers/new", payload)
        if not isinstance(rv, dict) or "offer_id" not in rv:
            raise BasicSwapAPIError(f"unexpected response from /json/offers/new: {rv!r}")
        return rv["offer_id"]

    def revoke_offer(self, offer_id: str, refuse_if_negotiating: bool = True) -> None:
        """Revokes (cancels) a live offer by hex id. `refuse_if_negotiating=True`
        (default) makes BasicSwap refuse the revoke if a bid on this offer is
        already mid-negotiation, rather than yanking it out from under a
        counterparty who's part-way into accepting it."""
        url = f"{self.base_url}/json/revokeoffer/{offer_id}"
        body = json.dumps({"refuse_if_negotiating": refuse_if_negotiating}).encode("utf-8")
        req = urllib.request.Request(
            url, data=body, method="POST", headers={"Content-Type": "application/json"}
        )
        self._request(req, url)

    def post_bid(self, offer_id: str, amount_from: str, bid_rate: str) -> str:
        """Submits a real bid into someone ELSE's live offer, at exactly their
        posted rate (bid_rate is passed through unchanged, never negotiated —
        see next_steps.md §8's rate_negotiable danger note, same posture as
        post_offer()'s automation_strat_id choice). amount_from is in the
        OFFER's own coin_from units (how much of what they're selling we want),
        not our own paying currency — the server computes what we owe in the
        offer's coin_to from amount_from * bid_rate.

        This is NOT reversible the way post_offer()/revoke_offer() are (see
        this module's docstring and bid_scanner.py's own docstring) — it
        actually starts a real atomic swap and commits capital for the swap's
        full duration. Returns the new bid's id (hex string).
        """
        payload: dict[str, Any] = {
            "offer_id": offer_id,
            "amount_from": amount_from,
            "bid_rate": bid_rate,
        }
        rv = self._post("/json/bids/new", payload)
        if not isinstance(rv, dict) or "bid_id" not in rv:
            raise BasicSwapAPIError(f"unexpected response from /json/bids/new: {rv!r}")
        return rv["bid_id"]

    def get_bids(self) -> list[dict]:
        """Read-only list of bids RECEIVED on our own offers, each with
        bid_id/offer_id/bid_state/amounts/created_at. Used by fill_ledger.py to
        tell fills from expiries. Checked live 2026-09-28: bids this node SENT
        (topup_xmr.py, bid_scanner.py) are not in here; see get_sent_bids()."""
        rv = self._get("/json/bids", {})
        if not isinstance(rv, list):
            raise BasicSwapAPIError(f"unexpected response from /json/bids: {rv!r}")
        return rv

    def get_sent_bids(self) -> list[dict]:
        """Read-only list of bids this node SENT into other makers' offers
        (/json/sentbids), same fields as get_bids(). coin_from/coin_to and the
        amounts are the OFFER's direction, so for us it's the reverse: we give
        amount_to of coin_to and receive amount_from of coin_from."""
        rv = self._post("/json/sentbids", {})
        if not isinstance(rv, list):
            raise BasicSwapAPIError(f"unexpected response from /json/sentbids: {rv!r}")
        return rv

    def get_bid(self, bid_id: str) -> dict:
        """Read-only detail for one bid (ours or received), keyed by hex id —
        includes 'bid_state' (a BidStates value as a display string, e.g.
        "Completed"/"Abandoned"/"Sent") via describeBid(). Used by
        bid_scanner.reconcile_bid_outcomes() to learn what actually happened
        to a bid post_bid() submitted, since post_bid()'s own response only
        confirms submission, not outcome."""
        rv = self._post(f"/json/bids/{bid_id}", {})
        if not isinstance(rv, dict) or "bid_state" not in rv:
            raise BasicSwapAPIError(f"unexpected response from /json/bids/{bid_id}: {rv!r}")
        return rv

    def get_rate(self, coin_from: str, coin_to: str) -> list:
        """External reference rate BasicSwap looks up for coin_from/coin_to — used
        as the "mid price" candidate offers are measured against, not itself an
        order-book value.

        Response is a list of one tuple-as-array per rate source, e.g. on success:
            [["coingecko.com", "XMR", "BTC", "123.45", "0.00012345", "0.00181818"]]
        (last element is the coin_to-per-coin_from rate) or on failure:
            [["coingecko.com", "error", "<message>"]]
        See storage._extract_rate for the parser — this deliberately doesn't raise
        on a per-source failure, since that's a legitimate (if unsuccessful) BasicSwap
        response, not an API/transport error.
        """
        return self._get("/json/rateslist", {"from": coin_from, "to": coin_to})
