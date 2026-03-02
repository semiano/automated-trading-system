import numpy as np
import pandas as pd

from mdtas.indicators.bollinger import compute_bollinger


def test_bollinger_ddof_zero():
    df = pd.DataFrame({"close": [1, 2, 3, 4, 5]})
    bb = compute_bollinger(df, length=5, stdev=2.0)
    expected_mid = 3.0
    expected_std = np.std([1, 2, 3, 4, 5], ddof=0)
    assert bb.iloc[-1]["bb_mid"] == expected_mid
    assert abs(bb.iloc[-1]["bb_upper"] - (expected_mid + 2 * expected_std)) < 1e-9
