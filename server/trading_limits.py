from decimal import Decimal


# Global safety ceiling. Event configs may request a lower price, but never a
# higher one. A contract priced exactly at 90 cents remains eligible.
HARD_MAX_BUY_PRICE = Decimal("0.9000")
