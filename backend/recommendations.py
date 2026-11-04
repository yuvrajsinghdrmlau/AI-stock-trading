"""Bounded discovery basket; membership is not an investment recommendation."""
STARTER_SYMBOLS = ('RELIANCE', 'TCS', 'INFY', 'HDFCBANK', 'ICICIBANK', 'SBIN',
                   'BHARTIARTL', 'ITC', 'LT', 'HINDUNILVR', 'AXISBANK', 'KOTAKBANK',
                   'SUNPHARMA', 'MARUTI', 'M&M', 'TITAN', 'ASIANPAINT', 'BAJFINANCE',
                   'HCLTECH', 'WIPRO', 'NTPC', 'POWERGRID', 'ONGC', 'COALINDIA', 'BEL')


def discovery_basket(universe):
    instruments, missing = [], []
    for symbol in STARTER_SYMBOLS:
        matches = universe.search(symbol, 'NSE', 'CASH', 0, 100)['items']
        eligible = [r for r in matches if r['symbol'] == symbol and r.get('simple_equity')
                    and not r.get('suspended')]
        if len(eligible) == 1:
            instruments.append(eligible[0])
        else:
            missing.append(symbol)
    return instruments, missing
