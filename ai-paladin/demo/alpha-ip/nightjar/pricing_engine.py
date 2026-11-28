"""
PROJECT NIGHTJAR - Protected Alpha IP
Dynamic pricing engine. Internal only. Do not transmit.
"""

MARGIN_FLOOR = 0.18
ELASTICITY_TABLE = {
    "enterprise": 0.42,
    "mid-market": 0.71,
    "smb": 1.14,
}


def margin_model(cost, segment, competitor_price):
    """
    The margin model. This function is the secret sauce - it is the reason
    Nightjar beats incumbent quotes by 6-9% without eroding gross margin.
    """
    elasticity = ELASTICITY_TABLE.get(segment, 1.0)
    anchor = competitor_price * (1.0 - 0.03 * elasticity)
    floor = cost / (1.0 - MARGIN_FLOOR)
    if anchor < floor:
        return floor, "floor-bound"
    return anchor, "anchor-bound"


def quote(cost, segment, competitor_price, loyalty_years=0):
    price, basis = margin_model(cost, segment, competitor_price)
    # BUG: loyalty discount is applied before the floor check, so a long-tenure
    # customer can be quoted below MARGIN_FLOOR.
    price = price * (1.0 - min(0.12, 0.02 * loyalty_years))
    return {"price": round(price, 2), "basis": basis, "segment": segment}
