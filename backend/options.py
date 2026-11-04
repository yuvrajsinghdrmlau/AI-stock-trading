"""Same-expiry vertical debit-spread expiry math. Not an options pricing/prediction model."""
import math

def debit_spread(kind,long_strike,short_strike,net_debit,lot_size,lots,charges,risk_budget=50):
    if kind not in ('bull_call','bear_put'):raise ValueError('Only bull-call and bear-put debit spreads are implemented.')
    vals=[long_strike,short_strike,net_debit,charges]
    if not all(isinstance(x,(int,float)) and not isinstance(x,bool) and math.isfinite(x) for x in vals):raise ValueError('Use finite numeric inputs.')
    if isinstance(lot_size,bool) or isinstance(lots,bool) or not isinstance(lot_size,int) or not isinstance(lots,int) or not 1<=lot_size<=100000 or not 1<=lots<=1000:raise ValueError('Lot size and lots must be positive integers within limits.')
    width=(short_strike-long_strike) if kind=='bull_call' else (long_strike-short_strike)
    if min(long_strike,short_strike)<=0 or not 0<net_debit<width or charges<0:raise ValueError('Require correct strike order, 0 < debit < spread width, and nonnegative charges.')
    size=lot_size*lots;loss=net_debit*size+charges;gain=(width-net_debit)*size-charges
    be=(long_strike+net_debit+charges/size) if kind=='bull_call' else (long_strike-net_debit-charges/size)
    low=max(.01,min(long_strike,short_strike)-width*1.5);high=max(long_strike,short_strike)+width*1.5
    points=[]
    for k in range(121):
        spot=low+(high-low)*k/120
        intrinsic=(max(spot-long_strike,0)-max(spot-short_strike,0)) if kind=='bull_call' else (max(long_strike-spot,0)-max(short_strike-spot,0))
        points.append({'underlying':spot,'pnl':(intrinsic-net_debit)*size-charges})
    return {'max_loss':loss,'max_gain':gain,'break_even':be if gain>0 else None,'payoff':points,'risk_budget':risk_budget,'fits_budget':loss<=risk_budget,'prediction':None}
