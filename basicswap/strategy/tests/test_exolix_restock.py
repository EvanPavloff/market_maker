import unittest
from unittest.mock import MagicMock, patch

from .. import exolix_restock as er
from .. import storage
from ..external_rates import ReferenceRate

NOW = 1_800_000_000.0
MID = 0.0071  # BTC per XMR
XMR_ADDR = "4A" + "1" * 93
BTC_ADDR = "bc1q" + "a" * 38
DEPOSIT = "bc1q" + "d" * 38
CFG = er.RestockConfig()


def _rate(kraken=MID, coingecko=MID, disagreement=0.0):
    return ReferenceRate("xmr", "btc", coingecko, kraken, disagreement, None, None)


def _client(xmr_balance=0.40, btc_balance=0.01, restock_bids=()):
    c = MagicMock()
    wallets = {
        "xmr": {"balance": str(xmr_balance), "unconfirmed": "0", "main_address": XMR_ADDR},
        "btc": {"balance": str(btc_balance), "unconfirmed": "0", "deposit_address": BTC_ADDR},
    }
    c.get_wallet.side_effect = lambda coin: wallets[coin]
    c.get_bids.return_value = list(restock_bids)
    c.get_sent_bids.return_value = []
    c.withdraw.return_value = "txid123"
    return c


def _exolix(xmr_per_btc=None):
    x = MagicMock()
    # Default quote: 0.6% worse than mid, before the network fee.
    per_btc = xmr_per_btc or 1 / (MID * 1.006)
    x.rate.side_effect = lambda amt: {"toAmount": amt * per_btc}
    x.create.side_effect = lambda amt, wa, ra: {
        "id": "ex1", "amount": amt, "amountTo": amt * per_btc, "depositAddress": DEPOSIT,
        "withdrawalAddress": wa, "coinFrom": {"coinCode": "BTC"}, "coinTo": {"coinCode": "XMR"}, "status": "wait",
    }
    return x


def _row(**kw):
    row = {"exolix_id": "ex0", "created_at": NOW - 3600, "updated_at": NOW - 3600, "status": "sent",
           "amount_btc": 0.0039, "quoted_xmr": 0.545, "reference_mid": MID, "all_in_premium_pct": 0.007,
           "deposit_address": DEPOSIT, "withdrawal_address": XMR_ADDR}
    row.update(kw)
    return row


@patch("strategy.external_rates.get_reference_rate", return_value=_rate())
class PlanTests(unittest.TestCase):
    def setUp(self):
        self.conn = storage.connect(":memory:")

    def test_stocked_wallet_does_nothing(self, _):
        p = er.plan(_client(xmr_balance=0.385 + 0.3), self.conn, _exolix(), CFG, NOW)
        self.assertEqual(p["action"], "none")

    def test_low_stock_swaps_up_to_target_within_caps(self, _):
        p = er.plan(_client(xmr_balance=0.40), self.conn, _exolix(), CFG, NOW)
        self.assertEqual(p["action"], "swap")
        self.assertAlmostEqual(p["need_xmr"], 0.385 + 0.55 - 0.40)
        self.assertLessEqual(p["amount_btc"], CFG.max_btc_per_swap)
        self.assertLess(p["premium"], CFG.max_premium_pct)

    def test_amount_is_capped_per_swap(self, _):
        p = er.plan(_client(xmr_balance=0.0), self.conn, _exolix(), CFG, NOW)
        self.assertEqual(p["amount_btc"], CFG.max_btc_per_swap)

    def test_expensive_quote_is_skipped(self, _):
        p = er.plan(_client(), self.conn, _exolix(xmr_per_btc=1 / (MID * 1.02)), CFG, NOW)
        self.assertEqual(p["action"], "skip")
        self.assertIn("all-in", p["reason"])

    def test_restock_offer_swap_in_flight_is_skipped(self, _):
        bid = {"coin_from": "Bitcoin", "coin_to": "Monero", "bid_state": "Bid Accepted"}
        p = er.plan(_client(restock_bids=[bid]), self.conn, _exolix(), CFG, NOW)
        self.assertEqual(p["action"], "skip")

    def test_daily_cap(self, _):
        for i in range(CFG.max_swaps_per_day):
            storage.insert_exolix_swap(self.conn, _row(exolix_id=f"d{i}", status="success",
                                                       created_at=NOW - 7200, updated_at=NOW - 7200))
        p = er.plan(_client(), self.conn, _exolix(), CFG, NOW)
        self.assertEqual(p["action"], "skip")
        self.assertIn("24h", p["reason"])

    def test_weekly_btc_cap(self, _):
        for i in range(4):
            storage.insert_exolix_swap(self.conn, _row(exolix_id=f"w{i}", status="success", amount_btc=0.0035,
                                                       created_at=NOW - 3 * 86400, updated_at=NOW - 3 * 86400))
        p = er.plan(_client(), self.conn, _exolix(), CFG, NOW)
        self.assertEqual(p["action"], "skip")
        self.assertIn("7 days", p["reason"])

    def test_cooldown_after_success(self, _):
        storage.insert_exolix_swap(self.conn, _row(status="success", updated_at=NOW - 600))
        self.assertEqual(er.plan(_client(), self.conn, _exolix(), CFG, NOW)["action"], "none")

    def test_btc_floor(self, _):
        p = er.plan(_client(btc_balance=0.003), self.conn, _exolix(), CFG, NOW)
        self.assertEqual(p["action"], "skip")

    def test_source_disagreement_skips(self, rate):
        rate.return_value = _rate(disagreement=0.05)
        self.assertEqual(er.plan(_client(), self.conn, _exolix(), CFG, NOW)["action"], "skip")


@patch("strategy.external_rates.get_reference_rate", return_value=_rate())
@patch.object(er, "_notify")
class ExecuteTests(unittest.TestCase):
    def setUp(self):
        self.conn = storage.connect(":memory:")

    def _plan(self, client, exolix):
        p = er.plan(client, self.conn, exolix, CFG, NOW)
        self.assertEqual(p["action"], "swap")
        return p

    def test_records_row_before_sending_then_marks_sent(self, *_):
        client, exolix = _client(), _exolix()
        seen_at_send = []
        client.withdraw.side_effect = lambda *a: seen_at_send.append(storage.fetch_exolix_swaps(self.conn)[0]["status"]) or "tx"
        self.assertIsNone(er.execute(client, self.conn, exolix, CFG, self._plan(client, exolix), NOW))
        self.assertEqual(seen_at_send, ["created"])
        client.withdraw.assert_called_once()
        self.assertEqual(client.withdraw.call_args.args[1], DEPOSIT)
        row = storage.fetch_exolix_swaps(self.conn)[0]
        self.assertEqual((row["status"], row["btc_txid"]), ("sent", "tx"))

    def test_wrong_withdrawal_address_sends_nothing_and_halts(self, *_):
        client, exolix = _client(), _exolix()
        p = self._plan(client, exolix)
        exolix.create.side_effect = lambda amt, wa, ra: {
            "id": "ex1", "amount": amt, "amountTo": 0.5, "depositAddress": DEPOSIT, "withdrawalAddress": "4B" + "2" * 93}
        self.assertIn("not our XMR address", er.execute(client, self.conn, exolix, CFG, p, NOW))
        client.withdraw.assert_not_called()

    def test_bad_deposit_address_sends_nothing(self, *_):
        client, exolix = _client(), _exolix()
        p = self._plan(client, exolix)
        exolix.create.side_effect = lambda amt, wa, ra: {
            "id": "ex1", "amount": amt, "amountTo": 0.5, "depositAddress": "0xdeadbeef", "withdrawalAddress": wa}
        self.assertIsNotNone(er.execute(client, self.conn, exolix, CFG, p, NOW))
        client.withdraw.assert_not_called()

    def test_quote_moved_over_cap_at_create_is_not_funded(self, *_):
        client, exolix = _client(), _exolix()
        p = self._plan(client, exolix)
        exolix.create.side_effect = lambda amt, wa, ra: {
            "id": "ex1", "amount": amt, "amountTo": amt / (MID * 1.03), "depositAddress": DEPOSIT, "withdrawalAddress": wa}
        self.assertIsNone(er.execute(client, self.conn, exolix, CFG, p, NOW))
        client.withdraw.assert_not_called()
        self.assertEqual(storage.fetch_exolix_swaps(self.conn)[0]["status"], "failed")

    def test_send_failure_is_recorded_and_halts(self, *_):
        client, exolix = _client(), _exolix()
        p = self._plan(client, exolix)
        client.withdraw.side_effect = TimeoutError("node timed out")
        self.assertIn("unknown", er.execute(client, self.conn, exolix, CFG, p, NOW))
        self.assertEqual(storage.fetch_exolix_swaps(self.conn)[0]["status"], "send_error")

    def test_bad_own_xmr_address_sends_nothing(self, *_):
        client, exolix = _client(), _exolix()
        p = self._plan(client, exolix)
        client.get_wallet.side_effect = lambda coin: {"balance": "1", "main_address": "8subaddr", "deposit_address": BTC_ADDR}
        self.assertIsNotNone(er.execute(client, self.conn, exolix, CFG, p, NOW))
        exolix.create.assert_not_called()


class ReconcileTests(unittest.TestCase):
    def setUp(self):
        self.conn = storage.connect(":memory:")
        self.exolix = MagicMock()

    def test_success_records_delivery(self):
        storage.insert_exolix_swap(self.conn, _row())
        self.exolix.get.return_value = {"status": "success", "amountTo": 0.544}
        self.assertEqual(er.reconcile(self.conn, self.exolix, CFG, NOW), (None, False))
        row = storage.fetch_exolix_swaps(self.conn)[0]
        self.assertEqual((row["status"], row["delivered_xmr"]), ("success", 0.544))

    def test_short_delivery_halts(self):
        storage.insert_exolix_swap(self.conn, _row())
        self.exolix.get.return_value = {"status": "success", "amountTo": 0.50}
        self.assertIsNotNone(er.reconcile(self.conn, self.exolix, CFG, NOW)[0])

    def test_pending_waits_then_times_out(self):
        storage.insert_exolix_swap(self.conn, _row())
        self.exolix.get.return_value = {"status": "exchanging"}
        self.assertEqual(er.reconcile(self.conn, self.exolix, CFG, NOW), (None, True))
        self.assertIsNotNone(er.reconcile(self.conn, self.exolix, CFG, NOW + 5 * 3600)[0])

    def test_refunded_halts(self):
        storage.insert_exolix_swap(self.conn, _row())
        self.exolix.get.return_value = {"status": "refunded"}
        self.assertIn("refunded", er.reconcile(self.conn, self.exolix, CFG, NOW)[0])

    def test_created_or_send_error_row_halts(self):
        for status in ("created", "send_error"):
            conn = storage.connect(":memory:")
            storage.insert_exolix_swap(conn, _row(status=status))
            self.assertIsNotNone(er.reconcile(conn, self.exolix, CFG, NOW)[0])
        self.exolix.get.assert_not_called()

    def test_lookup_error_retries_until_timeout(self):
        storage.insert_exolix_swap(self.conn, _row())
        self.exolix.get.side_effect = er.ExolixError("down")
        self.assertEqual(er.reconcile(self.conn, self.exolix, CFG, NOW), (None, True))
        self.assertIsNotNone(er.reconcile(self.conn, self.exolix, CFG, NOW + 5 * 3600)[0])


class MainTests(unittest.TestCase):
    def test_halt_file_stops_everything(self):
        with patch.object(er, "HALT_FILE", __file__), patch.object(er, "load_config") as lc:
            self.assertEqual(er.main([]), 1)
            lc.assert_not_called()


if __name__ == "__main__":
    unittest.main()
