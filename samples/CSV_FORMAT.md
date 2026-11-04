# Import format

Required headers (case-insensitive): `Timestamp,Open,High,Low,Close,Volume`.
Alternative timestamp headers `Date` or `Datetime` are also accepted.

Daily example timestamp: `2026-10-30T00:00:00+05:30`.
Intraday example: `2026-10-30T09:15:00+05:30` for the **opening** of a 15-minute bar.
Naive timestamps are interpreted as IST. Do not label end-of-bar timestamps as starts.

Use your authorized, genuine OHLCV history. At least 70 complete bars are needed to import;
a statistically usable study generally needs much more history and enough examples of both outcomes.
Max 15,000 bars and 4 MB per CSV. Numeric values must be finite; volume nonnegative;
OHLC values positive and internally consistent. Duplicate timestamps are rejected.
Incomplete bars are withheld. Intraday weekends and times outside 09:15-15:15 are rejected.
The app does not contain a full NSE holiday calendar or independently verify corporate actions.

No fabricated real-stock history is bundled. SIM-* demo datasets are generated inside the application.
Imported CSV provenance remains unverified: importing it is not certification of its authenticity.
