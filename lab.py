"""BTC Race v2 — Backtest Lab (offline, exact bars-replay/v1 fill model).

Fill model (competition.yaml / RULES.txt, verified: reproduces v1's official
dev grade +$6.47 / 2 trades exactly):
- order decided on bar k fills at bar k+1 open
- buy: fee 4 bps on notional; fill = open*(1+2bps)*(1+a/D), a = notional-less-fee
- sell: fill = open*(1-2bps)/(1+a/D); fee 4 bps on gross proceeds
- max_slippage 100 bps vs latest close; end flatten at last close vs c_depth
- fee_mult scales fee+slippage for cost-sensitivity tests (2x fee test).

Bars carry o/h/l/c + depths only. Volume is null (v=None) by design:
RULES.txt "volume is null (pool state carries none)" and the ADX baseline notes
"a bar's v, 0 or null, holds nothing back". Volume confirmation is therefore
implemented with the documented price-based proxy: bar-range expansion
(h-l vs ATR) + next-bar follow-through, never invented volume.
"""
import gzip, json, math, statistics, sys

KIT = '/home/hatch/workspace/makefun/btc-race-20261118-1444/btc-race-24h-20261118-1444-kit'
DATA = KIT + '/dataset/bars/CBBTC.ndjson.gz'

def load_bars(path=DATA):
    rows = [json.loads(l) for l in gzip.open(path, 'rt')]
    return {
        'o': [int(r['o']) / 1e5 for r in rows],
        'h': [int(r['h']) / 1e5 for r in rows],
        'l': [int(r['l']) / 1e5 for r in rows],
        'c': [int(r['c']) / 1e5 for r in rows],
        'o_depth': [int(r['o_depth'][0]) for r in rows],
        'c_depth': [int(r['c_depth'][0]) for r in rows],
        'n': len(rows),
    }

BARS = load_bars()
O, H, L, C = BARS['o'], BARS['h'], BARS['l'], BARS['c']
OD, CD, N = BARS['o_depth'], BARS['c_depth'], BARS['n']

# ---------------- indicators ----------------
def ema(s, p):
    k = 2.0 / (p + 1); out = [s[0]]
    for x in s[1:]:
        out.append(out[-1] + k * (x - out[-1]))
    return out

def sma(s, p):
    out, acc = [], 0.0
    for i, x in enumerate(s):
        acc += x
        if i >= p:
            acc -= s[i - p]
        out.append(acc / min(i + 1, p))
    return out

def rsi_wilder(closes, period=14):
    r = [None] * len(closes); ag = al = None
    gains, losses = [0.0], [0.0]
    for i in range(1, len(closes)):
        ch = closes[i] - closes[i - 1]
        gains.append(max(ch, 0.0)); losses.append(max(-ch, 0.0))
        if i == period:
            ag = sum(gains[1:period + 1]) / period; al = sum(losses[1:period + 1]) / period
        elif i > period:
            ag = (ag * (period - 1) + gains[i]) / period
            al = (al * (period - 1) + losses[i]) / period
        if ag is not None:
            r[i] = 50.0 if ag + al == 0 else 100 * ag / (ag + al)
    return r

def atr_wilder(period=14):
    trs = [H[0] - L[0]]
    for i in range(1, N):
        trs.append(max(H[i] - L[i], abs(H[i] - C[i - 1]), abs(L[i] - C[i - 1])))
    out = [None] * N
    a = sum(trs[:period]) / period
    out[period - 1] = a
    for i in range(period, N):
        a = (a * (period - 1) + trs[i]) / period
        out[i] = a
    return out

def macd(closes, fast=12, slow=26, sig=9):
    ef, es = ema(closes, fast), ema(closes, slow)
    line = [a - b for a, b in zip(ef, es)]
    return line, ema(line, sig)

EMA8, EMA9, EMA21, EMA50 = ema(C, 8), ema(C, 9), ema(C, 21), ema(C, 50)
SMA50, SMA120 = sma(C, 50), sma(C, 120)
RSI = rsi_wilder(C, 14)
ATR = atr_wilder(14)
MACD_LINE, MACD_SIG = macd(C)
TYP = [(H[i] + L[i] + C[i]) / 3 for i in range(N)]
BB_LO, BB_UP = [None] * N, [None] * N
for i in range(19, N):
    w = TYP[i - 19:i + 1]; m = sum(w) / 20
    sd = math.sqrt(sum((x - m) ** 2 for x in w) / 20)
    BB_LO[i], BB_UP[i] = m - 2 * sd, m + 2 * sd

# ---------------- window handling ----------------
# Indicators are module globals computed from the active window. The full
# 1440-bar dev window is the default; set_window() installs a slice (used
# for the chronological train/validation split) and recomputes every
# indicator from that slice alone, so no future information leaks in.
def set_window(o, h, l, c, od, cd):
    global O, H, L, C, OD, CD, N
    global EMA8, EMA9, EMA21, EMA50, SMA50, SMA120, RSI, ATR
    global MACD_LINE, MACD_SIG, TYP, BB_LO, BB_UP
    O, H, L, C, OD, CD, N = o, h, l, c, od, cd, len(c)
    EMA8, EMA9, EMA21, EMA50 = ema(C, 8), ema(C, 9), ema(C, 21), ema(C, 50)
    SMA50, SMA120 = sma(C, 50), sma(C, 120)
    RSI = rsi_wilder(C, 14)
    ATR = atr_wilder(14)
    MACD_LINE, MACD_SIG = macd(C)
    TYP = [(H[i] + L[i] + C[i]) / 3 for i in range(N)]
    BB_LO, BB_UP = [None] * N, [None] * N
    for i in range(19, N):
        w = TYP[i - 19:i + 1]; m = sum(w) / 20
        sd = math.sqrt(sum((x - m) ** 2 for x in w) / 20)
        BB_LO[i], BB_UP[i] = m - 2 * sd, m + 2 * sd

def subbars(a, b):
    """bars[a:b] of the ORIGINAL full window (for set_window)."""
    return (O[a:b], H[a:b], L[a:b], C[a:b], OD[a:b], CD[a:b])

def logret(i, k):
    return math.log(C[i] / C[i - k]) if i >= k else -1e9

def clamp(x, lo, hi):
    return max(lo, min(hi, x))

# ---------------- simulator ----------------
def simulate(entry_fn, exit_fn, size_frac=1.0, warmup=120,
             cooldown=0, insurance_bar=None, insurance_frac=0.05,
             start_cash=1000.0, fee_mult=1.0):
    """entry_fn(i, ctx)->bool buy; exit_fn(i, ctx)->bool sell (whole position).
    Prices/indicators come from the active window (see set_window).
    ctx: cash, qty, entry_fill, entry_close, peak, held, equity, i, atr_bps."""
    o, c, od, cd = O, C, OD, CD
    n = len(c)
    fee_bps = 0.0004 * fee_mult
    slip_bps = 0.0002 * fee_mult
    cash, qty = start_cash, 0.0
    peak = 0.0; entry_fill = 0.0; entry_close = 0.0; held = 0
    has_fill = False; trades = 0; total_fees = 0.0
    peak_eq, max_dd = start_cash, 0.0
    cool_until = -1; pending = None; log = []
    block_pnl = [0.0] * 24
    prev_eq = start_cash

    def apply_fill(i):
        nonlocal cash, qty, has_fill, trades, total_fees
        if pending is None:
            return None
        side, amt = pending
        op, dep = o[i], od[i]
        prev = c[i - 1] if i > 0 else op
        if side == 'buy':
            fee = amt * fee_bps
            a = (amt - fee) * 1e6
            fp = op * (1 + slip_bps) * (1 + a / dep)
            if fp > prev * 1.01:
                return None
            q = (amt - fee) / fp
            cash -= amt; qty += q; has_fill = True; trades += 1
            total_fees += fee
            log.append(('BUY', i, round(fp, 2)))
            return fp
        val = amt * op
        a = val * 1e6
        fp = op * (1 - slip_bps) / (1 + a / dep)
        if fp < prev * 0.99:
            return None
        proceeds = amt * fp
        fee = proceeds * fee_bps
        cash += proceeds - fee; qty -= amt; has_fill = True; trades += 1
        total_fees += fee
        log.append(('SELL', i, round(fp, 2)))
        return fp

    for i in range(n):
        fp = apply_fill(i)
        pending = None
        if fp is not None and qty > 0 and held == 0:
            entry_fill = fp
        close = c[i]
        eq = cash + qty * close
        block_pnl[i // 60] += eq - prev_eq
        prev_eq = eq
        if eq > peak_eq:
            peak_eq = eq
        dd = (peak_eq - eq) / start_cash
        if dd > max_dd:
            max_dd = dd
        atr_bps = (ATR[i] / close * 1e4) if ATR[i] else 5.0
        ctx = dict(cash=cash, qty=qty, entry_fill=entry_fill, entry_close=entry_close,
                   peak=peak, held=held, equity=eq, i=i, atr_bps=atr_bps)
        if qty > 0:
            held += 1
            if close > peak:
                peak = close
            if exit_fn(i, ctx):
                pending = ('sell', qty)
                cool_until = i + cooldown
                held = 0; peak = 0.0
            continue
        peak = 0.0; held = 0
        if i < warmup or i < cool_until:
            continue
        if insurance_bar is not None and not has_fill and i >= insurance_bar:
            stake = eq * insurance_frac
            if stake >= 1.0:
                pending = ('buy', stake); entry_close = close
            continue
        if entry_fn(i, ctx):
            amt = cash * size_frac
            if amt >= 1.0:
                pending = ('buy', amt); entry_close = close
    if qty > 0:
        op, dep = c[-1], cd[-1]
        val = qty * op
        fp = op * (1 - slip_bps) / (1 + val * 1e6 / dep)
        proceeds = qty * fp
        fee = proceeds * fee_bps
        cash += proceeds - fee
        total_fees += fee
        qty = 0.0
    pnl = cash - start_cash
    buys = [x for x in log if x[0] == 'BUY']; sells = [x for x in log if x[0] == 'SELL']
    rts = min(len(buys), len(sells))
    rt_rets = [math.log(sells[k][2] / buys[k][2]) * 1e4 for k in range(rts)]
    wins = sum(1 for r in rt_rets if r > 0)
    gw = sum(r for r in rt_rets if r > 0); gl = sum(-r for r in rt_rets if r <= 0)
    pf = (gw / gl) if gl > 0 else (float('inf') if gw > 0 else 0.0)
    return dict(pnl=pnl, ret=pnl / start_cash, trades=trades, roundtrips=rts,
                win_rate=(wins / rts if rts else 0.0), profit_factor=pf,
                max_dd=max_dd, total_fees=total_fees, log=log,
                avg_rt_bps=(statistics.mean(rt_rets) if rt_rets else 0.0),
                block_pnl=block_pnl)

def fmt(name, r):
    print('%-46s pnl $%7.2f ret %+6.2f%% win %.2f tr %3d rt %3d DD %.3f fees $%6.2f PF %5.2f' % (
        name, r['pnl'], r['ret'] * 100, r['win_rate'], r['trades'], r['roundtrips'],
        r['max_dd'], r['total_fees'], r['profit_factor']))
    return r

# ---------------- baselines (official kit logic) ----------------
def baseline_buy_hold(i, ctx):
    return i == 0

def baseline_hold_cash(i, ctx):
    return False

def baseline_momentum_24(i, ctx):
    # buys on batch 24 and holds (single asset: top-1 by trailing 24-bar return)
    return i == 24

def baseline_ema_cross_entry(i, ctx):
    return EMA8[i] > EMA21[i] and EMA8[i - 1] <= EMA21[i - 1] and i >= 21

def baseline_ema_cross_exit(i, ctx):
    if EMA8[i] < EMA21[i]:
        return True
    v = ctx['qty'] * C[i]
    cost = ctx['qty'] * ctx['entry_fill']
    if v >= cost * 1.5 or v <= cost * 0.8:
        return True
    return False

def baseline_rsi_bb_entry(i, ctx):
    return RSI[i] is not None and BB_LO[i] is not None and RSI[i] < 30 and C[i] < BB_LO[i]

def baseline_rsi_bb_exit(i, ctx):
    if RSI[i] is not None and RSI[i] > 70:
        return True
    if math.log(C[i] / ctx['entry_fill']) * 1e4 >= 1000:
        return True
    if math.log(C[i] / ctx['entry_fill']) * 1e4 <= -2500:
        return True
    return False

# ---------------- variants V1..V5 ----------------
# Shared ATR-adaptive exit: trail/TP/SL in bps, clamped to validated wide bands.
def atr_exit(i, ctx, trail_mult=20.0, tp_mult=30.0, sl_mult=40.0,
             trail_lo=80.0, trail_hi=150.0, tp_lo=120.0, tp_hi=250.0,
             sl_lo=150.0, sl_hi=300.0):
    a = ctx['atr_bps']
    trail = clamp(trail_mult * a, trail_lo, trail_hi)
    tp = clamp(tp_mult * a, tp_lo, tp_hi)
    sl = clamp(sl_mult * a, sl_lo, sl_hi)
    if ctx['peak'] > 0 and math.log(C[i] / ctx['peak']) * 1e4 <= -trail:
        return True
    if math.log(C[i] / ctx['entry_close']) * 1e4 >= tp:
        return True
    if math.log(C[i] / ctx['entry_close']) * 1e4 <= -sl:
        return True
    return False

# V1: EMA 8/21 crossover + EMA50 filter
def v1_entry(i, ctx):
    return (EMA8[i] > EMA21[i] and EMA8[i - 1] <= EMA21[i - 1]
            and C[i] > EMA50[i] and i >= 50)

def v1_exit(i, ctx):
    return atr_exit(i, ctx)

# V2: Momentum + RSI (RSI 14, MACD, rate of change; volume proxy = range expansion)
def v2_entry(i, ctx):
    if i < 50 or RSI[i] is None:
        return False
    mom = logret(i, 5) * 1e4 >= 30 or logret(i, 10) * 1e4 >= 50
    rsi_ok = 50 <= RSI[i] <= 75
    macd_ok = MACD_LINE[i] > MACD_SIG[i]
    rng_ok = (H[i] - L[i]) / C[i] * 1e4 >= 1.2 * ctx['atr_bps']
    return mom and rsi_ok and macd_ok and rng_ok and C[i] > EMA50[i]

def v2_exit(i, ctx):
    return atr_exit(i, ctx)

# V3: Breakout + volume proxy (rolling high, range expansion, false-breakout rejection)
def v3_entry(i, ctx):
    if i < 60:
        return False
    hi60 = max(C[i - 60:i])
    breakout = C[i] > hi60
    rng_ok = (H[i] - L[i]) / C[i] * 1e4 >= 1.5 * ctx['atr_bps']
    follow = logret(i, 5) * 1e4 >= 10
    return breakout and rng_ok and follow

def v3_exit(i, ctx):
    # false-breakout rejection: close back below the broken 60-bar high within 10 bars
    if ctx['held'] <= 10 and i >= 60 and C[i] < max(C[i - 60:i]):
        return True
    return atr_exit(i, ctx)

# V4: EMA + Momentum combined
def v4_entry(i, ctx):
    if i < 50 or RSI[i] is None:
        return False
    trend = EMA8[i] > EMA21[i] > EMA50[i]
    mom = logret(i, 5) * 1e4 >= 30 or logret(i, 10) * 1e4 >= 50
    return trend and mom and 45 <= RSI[i] <= 75

def v4_exit(i, ctx):
    return atr_exit(i, ctx)

def regime(i):
    if EMA8[i] > EMA21[i] > EMA50[i]:
        return 'up'
    if EMA8[i] < EMA21[i] < EMA50[i]:
        return 'down'
    return 'range'

# V5: Adaptive Multi-Strategy with per-engine weighted signal scoring.
# LESSON from the first V5 run (full window -$6.06): a single summed threshold
# blocked the one validated money-making signal — the deep-dip swing scores
# only 55 (dip 45 + RSI 10) because momentum/trend engines point the other
# way during a dip. Each engine is therefore scored independently and fires
# on its own validated threshold (>=70); engines never veto each other.
# Which engine fired is returned for transparency (see v5_engine()).
def v5_engine_scores(i, ctx):
    if i < 120 or RSI[i] is None:
        return {}
    scores = {}
    # Engine A — Trend (EMA 8/21 cross + EMA50 filter + persistence)
    a = 0
    if EMA8[i] > EMA21[i] and EMA8[i - 1] <= EMA21[i - 1] and C[i] > EMA50[i]:
        a += 40
    if regime(i) == 'up':
        a += 20
    if logret(i, 5) * 1e4 >= 30 or logret(i, 10) * 1e4 >= 50:
        a += 20
    scores['trend'] = a
    # Engine B — Momentum (RSI 14, MACD, ROC, range-expansion proxy for volume)
    b = 0
    if logret(i, 5) * 1e4 >= 30 or logret(i, 10) * 1e4 >= 50:
        b += 25
    if 50 <= RSI[i] <= 75 and MACD_LINE[i] > MACD_SIG[i]:
        b += 20
    if regime(i) == 'up':
        b += 20
    if (H[i] - L[i]) / C[i] * 1e4 >= 1.2 * ctx['atr_bps']:
        b += 10
    scores['momentum'] = b
    # Engine C — Breakout (rolling 60-bar high + range expansion + follow-through)
    c = 0
    if i >= 60 and C[i] > max(C[i - 60:i]):
        c += 40
    if (H[i] - L[i]) / C[i] * 1e4 >= 1.5 * ctx['atr_bps']:
        c += 20
    if logret(i, 5) * 1e4 >= 10:
        c += 15
    scores['breakout'] = c
    # Engine D — Volatility / deep-dip swing (validated +$16.65 trade shape:
    # drop >=150 bps from the 120-bar high, wide ATR trailing exit).
    d = 0
    if math.log(C[i] / max(C[i - 120:i])) * 1e4 <= -150:
        d += 50
    if RSI[i] < 40:
        d += 20
    scores['dip'] = d
    return scores

def v5_entry(i, ctx):
    return any(s >= 70 for s in v5_engine_scores(i, ctx).values())

def v5_exit(i, ctx):
    return atr_exit(i, ctx)

# V5-gated: dip engine fires in any regime; trend/momentum/breakout only in
# a confirmed uptrend (regime gate). Tests whether the losing engines can be
# silenced in the down/range regimes that dominate this window.
def v5g_entry(i, ctx):
    if i < 120 or RSI[i] is None:
        return False
    sc = v5_engine_scores(i, ctx)
    if sc.get('dip', 0) >= 70:
        return True
    if regime(i) == 'up':
        return any(sc.get(k, 0) >= 70 for k in ('trend', 'momentum', 'breakout'))
    return False

# COMBO (shipped v2): DIP engine (primary) + v1 momentum-burst engine
# (secondary, validated standalone +$6.47 with its own exit). Exits are
# per-engine and ATR-adaptive WITH floors/caps that reproduce the validated
# fixed-bps values at the dev window's typical ATR (~4.8 bps):
#   dip:   trail clamp(20*ATR, 80, 120) / TP clamp(40*ATR, 150, 250) /
#          SL clamp(60*ATR, 250, 350)   (~100/200/300 bps at ATR 4.8)
#   burst: trail clamp(13*ATR, 50, 80)  / TP clamp(20*ATR, 80, 120)
#          (~65/100 bps at ATR 4.8). A unified wide exit was tested and
#          REJECTED: v1-burst + wide exit loses -$1.13 (vs +$6.47 with its
#          own exit) because it holds too long and gives the gain back.
_COMBO_ENGINE = {'name': None}

def combo_entry(i, ctx):
    if i < 120:
        return False
    if math.log(C[i] / max(C[i - 120:i])) * 1e4 <= -150:
        _COMBO_ENGINE['name'] = 'dip'
        return True
    b = logret(i, 5) * 1e4 >= 60 or logret(i, 10) * 1e4 >= 80
    if b and C[i] > SMA120[i]:
        _COMBO_ENGINE['name'] = 'burst'
        return True
    return False

def combo_exit(i, ctx):
    a = ctx['atr_bps']
    if _COMBO_ENGINE['name'] == 'burst':
        trail = clamp(13 * a, 50, 80)
        tp = clamp(20 * a, 80, 120)
        if ctx['peak'] > 0 and math.log(C[i] / ctx['peak']) * 1e4 <= -trail:
            return True
        if math.log(C[i] / ctx['entry_close']) * 1e4 >= tp:
            return True
        return False
    trail = clamp(20 * a, 80, 120)
    tp = clamp(40 * a, 150, 250)
    sl = clamp(60 * a, 250, 350)
    if ctx['peak'] > 0 and math.log(C[i] / ctx['peak']) * 1e4 <= -trail:
        return True
    if math.log(C[i] / ctx['entry_close']) * 1e4 >= tp:
        return True
    if math.log(C[i] / ctx['entry_close']) * 1e4 <= -sl:
        return True
    return False

# DIP-only: the isolated deep-dip swing engine (drop>=150 bps from the
# 120-bar high; wide trailing 100 bps / TP +200 bps / SL -300 bps).
# Validated plateau (grid 27 cells): +$2.42..+$17.55, only 1 cell negative.
def dip_entry(i, ctx):
    if i < 120:
        return False
    return math.log(C[i] / max(C[i - 120:i])) * 1e4 <= -150

def dip_exit(i, ctx):
    if ctx['peak'] > 0 and math.log(C[i] / ctx['peak']) * 1e4 <= -100:
        return True
    if math.log(C[i] / ctx['entry_close']) * 1e4 >= 200:
        return True
    if math.log(C[i] / ctx['entry_close']) * 1e4 <= -300:
        return True
    return False

# SHIPPED v2 (main.py): dip + v1-burst with FIXED per-engine exits.
# This is the exact logic shipped in main.py (same thresholds, same exits,
# same cooldown/insurance). The ATR-adaptive COMBO above was tested and
# REJECTED (it exits the dip swing early: +$10.90 vs +$16.65 fixed).
_SHIPPED_ENGINE = {'name': None}

def shipped_entry(i, ctx):
    if i < 120:
        return False
    if math.log(C[i] / max(C[i - 120:i])) * 1e4 <= -150:
        _SHIPPED_ENGINE['name'] = 'dip'
        return True
    b = logret(i, 5) * 1e4 >= 60 or logret(i, 10) * 1e4 >= 80
    if b and C[i] > SMA120[i]:
        _SHIPPED_ENGINE['name'] = 'burst'
        return True
    return False

def shipped_exit(i, ctx):
    if _SHIPPED_ENGINE['name'] == 'burst':
        return v1orig_exit(i, ctx)
    return dip_exit(i, ctx)

# v1 original (submitted bot) for reference
def v1orig_entry(i, ctx):
    if i < 120:
        return False
    b = logret(i, 5) * 1e4 >= 60 or logret(i, 10) * 1e4 >= 80
    return b and C[i] > SMA120[i]

def v1orig_exit(i, ctx):
    if ctx['peak'] > 0 and math.log(C[i] / ctx['peak']) * 1e4 <= -65:
        return True
    if math.log(C[i] / ctx['entry_close']) * 1e4 >= 100:
        return True
    return False

if __name__ == '__main__':
    print('== LAB: full dev window (1440 bars) ==')
    print('--- official baselines ---')
    fmt('baseline buy-and-hold', simulate(baseline_buy_hold, lambda i, c: False, warmup=0))
    fmt('baseline hold-cash', simulate(baseline_hold_cash, lambda i, c: False, warmup=0))
    fmt('baseline momentum-24bar', simulate(baseline_momentum_24, lambda i, c: False, warmup=0))
    fmt('baseline ema-cross', simulate(baseline_ema_cross_entry, baseline_ema_cross_exit, warmup=21))
    fmt('baseline rsi-bollinger', simulate(baseline_rsi_bb_entry, baseline_rsi_bb_exit, warmup=20))
    print('--- submitted v1 (reference) ---')
    fmt('v1-submitted (60/80 burst, SMA120, trail65, TP100)',
        simulate(v1orig_entry, v1orig_exit, warmup=120,
                 insurance_bar=1380, insurance_frac=0.05))
    print('--- variants V1..V5 ---')
    results = {}
    results['V1 EMA 8/21'] = fmt('V1 EMA 8/21', simulate(v1_entry, v1_exit, warmup=50, cooldown=5,
                                                         insurance_bar=1380, insurance_frac=0.05))
    results['V2 Momentum+RSI'] = fmt('V2 Momentum+RSI', simulate(v2_entry, v2_exit, warmup=50, cooldown=5,
                                                                 insurance_bar=1380, insurance_frac=0.05))
    results['V3 Breakout+VolProxy'] = fmt('V3 Breakout+VolProxy', simulate(v3_entry, v3_exit, warmup=60, cooldown=5,
                                                                           insurance_bar=1380, insurance_frac=0.05))
    results['V4 EMA+Momentum'] = fmt('V4 EMA+Momentum', simulate(v4_entry, v4_exit, warmup=50, cooldown=5,
                                                                  insurance_bar=1380, insurance_frac=0.05))
    results['V5 Adaptive Multi'] = fmt('V5 Adaptive Multi-Strategy', simulate(v5_entry, v5_exit, warmup=120, cooldown=5,
                                                                              insurance_bar=1380, insurance_frac=0.05))
    results['V5-gated'] = fmt('V5-gated (dip any regime, rest uptrend only)', simulate(v5g_entry, v5_exit, warmup=120, cooldown=5,
                                                                                      insurance_bar=1380, insurance_frac=0.05))
    results['DIP-only'] = fmt('DIP-only (drop150, trail100, TP200, SL300)', simulate(dip_entry, dip_exit, warmup=120, cooldown=5,
                                                                                    insurance_bar=1380, insurance_frac=0.05))
    results['COMBO ATR-adaptive (tested, NOT shipped)'] = fmt('COMBO ATR-adaptive (dip + v1burst, per-engine ATR exits)', simulate(combo_entry, combo_exit, warmup=120, cooldown=5,
                                                                                                insurance_bar=1380, insurance_frac=0.05))
    results['SHIPPED v2 fixed exits'] = fmt('SHIPPED v2 (dip + v1burst, FIXED per-engine exits)', simulate(shipped_entry, shipped_exit, warmup=120, cooldown=5,
                                                                                                insurance_bar=1380, insurance_frac=0.05))
    print()
    print('== ROBUSTNESS: split-half (train bars 0-719 / validation 720-1439) ==')
    print('Each half is re-installed as its own window (indicators recomputed')
    print('from that half alone); each half starts at $1000.')
    FO, FH, FL, FC, FOD, FCD = O, H, L, C, OD, CD  # capture full window first
    for name, (en, ex, w) in {
        'v1-submitted': (v1orig_entry, v1orig_exit, 120),
        'V1 EMA 8/21': (v1_entry, v1_exit, 50),
        'V2 Momentum+RSI': (v2_entry, v2_exit, 50),
        'V3 Breakout': (v3_entry, v3_exit, 60),
        'V4 EMA+Momentum': (v4_entry, v4_exit, 50),
        'V5 Adaptive': (v5_entry, v5_exit, 120),
        'V5-gated': (v5g_entry, v5_exit, 120),
        'DIP-only': (dip_entry, dip_exit, 120),
        'COMBO ATR': (combo_entry, combo_exit, 120),
        'SHIPPED v2': (shipped_entry, shipped_exit, 120),
    }.items():
        set_window(FO[0:720], FH[0:720], FL[0:720], FC[0:720], FOD[0:720], FCD[0:720])
        r1 = simulate(en, ex, warmup=min(w, 100))
        set_window(FO[720:1440], FH[720:1440], FL[720:1440], FC[720:1440], FOD[720:1440], FCD[720:1440])
        r2 = simulate(en, ex, warmup=min(w, 100))
        print('%-18s H1(0-719) pnl $%7.2f tr %2d | H2(720-1439) pnl $%7.2f tr %2d' % (
            name, r1['pnl'], r1['trades'], r2['pnl'], r2['trades']))
    set_window(FO, FH, FL, FC, FOD, FCD)  # restore full window
    print('== ROBUSTNESS: 2x fee test (fee 8bps + slip 4bps) ==')
    for name, (en, ex, w) in {
        'v1-submitted': (v1orig_entry, v1orig_exit, 120),
        'V1 EMA 8/21': (v1_entry, v1_exit, 50),
        'V2 Momentum+RSI': (v2_entry, v2_exit, 50),
        'V3 Breakout': (v3_entry, v3_exit, 60),
        'V4 EMA+Momentum': (v4_entry, v4_exit, 50),
        'V5 Adaptive': (v5_entry, v5_exit, 120),
        'V5-gated': (v5g_entry, v5_exit, 120),
        'DIP-only': (dip_entry, dip_exit, 120),
        'COMBO ATR': (combo_entry, combo_exit, 120),
        'SHIPPED v2': (shipped_entry, shipped_exit, 120),
    }.items():
        r = simulate(en, ex, warmup=w, cooldown=5, fee_mult=2.0,
                     insurance_bar=1380, insurance_frac=0.05)
        print('%-18s 2x-fee pnl $%7.2f tr %2d' % (name, r['pnl'], r['trades']))
    print()
    print('== V5 per-hour-block PnL (full window) ==')
    r5 = results['V5 Adaptive Multi']
    print('blocks:', ['%+.2f' % x for x in r5['block_pnl']])
    print('positive blocks: %d/24' % sum(1 for x in r5['block_pnl'] if x > 0))
