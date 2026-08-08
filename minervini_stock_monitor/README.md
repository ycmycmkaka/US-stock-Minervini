# Minervini-style US Stock Monitor

## What it screens

Final matches must pass all of the following:

- US listed non-ETF common-stock universe
- Market cap >= $5B
- Minervini-style Trend Template = 8/8
- Custom RS percentile >= 80
- 20-day return relative to SPY >= 0%
- 60-day return relative to SPY >= 0%
- Within 15% of the 52-week high

The custom RS is not the proprietary IBD RS Rating. It ranks all market-cap-eligible stocks by a weighted momentum score: 40% 3-month + 20% 6-month + 20% 9-month + 20% 12-month cumulative return.

## Automatic update

`.github/workflows/update.yml` runs at 23:00 UTC every weekday and can also be run manually with **Actions > Update Minervini Stock Monitor > Run workflow**.

## Files to place in repository root

- `index.html`
- `style.css`
- `script.js`
- `config.json`
- `requirements.txt`
- `update_data.py`
- `results.json`

Also preserve the nested workflow path:

- `.github/workflows/update.yml`
