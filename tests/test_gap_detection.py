from datetime import datetime

import pandas as pd

from mdtas.ingestion.gaps import detect_gaps


def test_gap_detection_single_gap():
    df = pd.DataFrame(
        {
            "ts": [
                datetime(2026, 1, 1, 0, 1),
                datetime(2026, 1, 1, 0, 2),
                datetime(2026, 1, 1, 0, 4),
            ]
        }
    )
    gaps = detect_gaps(df, "1m")
    assert len(gaps) == 1
    assert gaps[0].start_ts == datetime(2026, 1, 1, 0, 3)
    assert gaps[0].end_ts == datetime(2026, 1, 1, 0, 3)
