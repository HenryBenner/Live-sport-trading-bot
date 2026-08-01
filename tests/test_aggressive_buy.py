from decimal import Decimal

from server.aggressive_buyer import AggressiveBuyError, AggressiveBuyer


class FakeKalshi:
    base_url = "https://example.invalid"
    subaccount = 0
    exchange_index = 0

    def _headers(self, method, endpoint):
        return {}


def book(*no_bid_levels):
    return {
        "orderbook_fp": {
            "yes_dollars": [],
            "no_dollars": [
                [str(price), str(count)] for price, count in no_bid_levels
            ],
        }
    }


def test_build_sweep_uses_multiple_levels_without_exceeding_cap():
    buyer = AggressiveBuyer(FakeKalshi())
    plan = buyer._build_sweep_order(
        orderbook=book(
            (Decimal("0.70"), Decimal("100")),
            (Decimal("0.60"), Decimal("100")),
        ),
        remaining_budget=Decimal("70"),
        maximum_buy_price=Decimal("1"),
        count_step=Decimal("1"),
    )
    assert plan == {"count": Decimal("175"), "price": Decimal("0.40")}
    assert plan["count"] * plan["price"] <= Decimal("70")


def test_submit_retries_same_client_id_after_rate_limit():
    buyer = AggressiveBuyer(FakeKalshi())
    seen_ids = []
    responses = iter(
        [
            AggressiveBuyError("rate limited", status_code=429),
            {
                "order_id": "order-1",
                "fill_count": "2.00",
                "remaining_count": "0.00",
                "average_fill_price": "0.4000",
                "average_fee_paid": "0.0010",
            },
        ]
    )

    def request(method, endpoint, json_body=None, timeout=5.0):
        seen_ids.append(json_body["client_order_id"])
        result = next(responses)
        if isinstance(result, Exception):
            raise result
        result["client_order_id"] = json_body["client_order_id"]
        return result

    buyer._request = request
    buyer._recover_order = lambda client_order_id: None
    buyer._sleep = lambda **kwargs: None

    result, errors = buyer._submit_with_retries(
        ticker="TEST",
        count=Decimal("2"),
        price=Decimal("0.40"),
        client_order_id="same-id",
        deadline=10**12,
        error_limit=3,
        retry_delay_seconds=0,
    )
    assert result["order_id"] == "order-1"
    assert len(errors) == 1
    assert seen_ids == ["same-id", "same-id"]
