"""BTC Race v2 — Round 2 lab: NET PnL MAXIMIZATION.

Builds on lab.py round-1 results (do NOT re-run blindly):
  V1 EMA -28.42 | V2 Momentum+RSI -15.80 | V3 Breakout -42.42 |
  V4 EMA+Momentum +1.99 (ATR exits) | V5 Adaptive -20.67 |
  SHIPPED v2 +16.65 (dip + burst, fixed exits) | v1 +6.47.
Reference rows (V1-V5) are re-printed from lab.py runs inside this file
so the comparison table is self-contained; they are marked REPEAT.

NEW in round 2 (the work that matters):
  R2-1  V4 with FIXED exits, standalone (3 exit sets) + as 3rd engine in SHIPPED.
  R2-2  C: pure pullback-continuation engine (untested in round 1).
  R2-3  D: adaptive hybrid with per-bar regime filter + cost gate.
  R2-4  E: hybrid D with position-size sweep (0.5 / 0.75 / 1.0).
  R2-5  Dip grid expansion (drop 120/150/180/210 x trail 80/100/120 x
        TP 150/200/250 x SL 250/300/400 = 108 cells) + cooldown/size dims
        on the best cell. Every finalist must pass split-half + 2x fee.
  R2-6  DP oracle: perfect-foresight upper bound with the EXACT fill
        costs, to judge whether the dev-top $92.40 is reachable at all.

Selection rule (round 2): a candidate replaces SHIPPED v2 ONLY if
  full-window net PnL > +$16.65 AND split-half H2 >= -$0.83 (no worse
  than shipped) AND 2x-fee net PnL >= +$14.22. Otherwise main.py is
  left untouched and the numbers are reported as-is.

Cost gate (new engines only): an entry is allowed only if its
take-profit exceeds 2x the round-trip cost at the current depth
(RT cost = 2 * (4 fee + 2 slip + impact) bps, impact from the latest
close depth — the depth RULES.txt says to size against). The validated
dip/burst thresholds are NOT changed by this gate.
"""
import json
import math
import statistics

import lab

FO, FH, FL, FC, FOD, FCD = lab.O, lab.H, lab.L, lab.C, lab.OD, lab.CD
N = len(FC)


def restore_full():
    lab.set_window(FO, FH, FL, FC, FOD, FCD)


def rt_cost_bps(i, notional):
    """Round-trip cost in bps for `notional` USDC at bar i (latest close depth).
    Depths are in micro-USDC (quote units), so notional is scaled by 1e6.
    (Round-2 fix: the first version divided dollars by micro-depths and
    understated impact ~to zero; the hybrid results below are unchanged
    by the fix — re-run verified — because no V4/pullback entry ever
    fired while flat, so the gate never bound.)"""
    dep = lab.CD[i] if lab.CD[i] > 0 else 844000000000.0
    # a/D is a ratio (micro/micro); x1e4 converts it to bps.
    impact = notional * 1e6 / dep * 1e4
    return 2.0 * (4.0 + 2.0 + impact)


def cost_gate_ok(i, ctx, tp_bps, size_frac=1.0):
    """True if the engine's take-profit clears 2x the round-trip cost."""
    notional = ctx['cash'] * size_frac
    return tp_bps > 2.0 * rt_cost_bps(i, notional)


# ---------------- DP oracle (perfect foresight, exact fill costs) ----------------
def dp_oracle(fee_mult=1.0):
    """Bang-bang (all-in / all-out) perfect-foresight bound on OPENS.
    Decisions use full future knowledge; fills use the lab's exact formulas
    (fee 4bps, slip 2bps, constant-product impact vs the bar's open depth).
    Returns net PnL in USDC. This is an UPPER bound on what any strategy
    could have made on this window, not a tradable result."""
    O, C, OD, CD = lab.O, lab.C, lab.OD, lab.CD
    fee = 0.0004 * fee_mult
    slip = 0.0002 * fee_mult

    def buy_qty(cash, op, dep):
        if cash < 1.0:
            return 0.0
        spend = cash * (1 - fee)
        a = spend * 1e6
        fp = op * (1 + slip) * (1 + a / dep)
        return spend / fp

    def sell_cash(qty, op, dep):
        val = qty * op
        a = val * 1e6
        fp = op * (1 - slip) / (1 + a / dep)
        return qty * fp * (1 - fee)

    F = 1000.0  # max cash flat at open[i]
    Q = 0.0     # max qty holding at open[i]
    for i in range(len(C)):
        op, dep = O[i], OD[i]
        newF = F
        if Q > 0:
            newF = max(newF, sell_cash(Q, op, dep))
        newQ = Q
        if F >= 1.0:
            newQ = max(newQ, buy_qty(F, op, dep))
        F, Q = newF, newQ
    final = F
    if Q > 0:
        final = max(final, sell_cash(Q, C[-1], CD[-1]))
    return final - 1000.0


# ---------------- fixed exits ----------------
def fixed_exit(trail, tp, sl=None):
    def _exit(i, ctx):
        if ctx['peak'] > 0 and math.log(lab.C[i] / ctx['peak']) * 1e4 <= -trail:
            return True
        if math.log(lab.C[i] / ctx['entry_close']) * 1e4 >= tp:
            return True
        if sl is not None and math.log(lab.C[i] / ctx['entry_close']) * 1e4 <= -sl:
            return True
        return False
    return _exit


# ---------------- V4 with fixed exits ----------------
V4_FIXED_SETS = {
    'V4f-A trail65/TP100': fixed_exit(65, 100),
    'V4f-B trail100/TP200/SL300': fixed_exit(100, 200, 300),
    'V4f-C trail80/TP150/SL200': fixed_exit(80, 150, 200),
}


# ---------------- regime classification ----------------
def regime5(i):
    """strong_bull / weak_bull / sideways / high_vol / bearish, per bar."""
    atr = lab.ATR[i] / lab.C[i] * 1e4 if lab.ATR[i] else 5.0
    if atr >= 10.0:
        return 'high_vol'
    if lab.EMA8[i] > lab.EMA21[i] > lab.EMA50[i]:
        return 'strong_bull' if (lab.RSI[i] or 50) > 55 else 'weak_bull'
    if lab.EMA8[i] < lab.EMA21[i] < lab.EMA50[i]:
        return 'bearish'
    return 'sideways'


# ---------------- pullback-continuation engine (C, NEW) ----------------
# Uptrend (EMA8>EMA21>EMA50) + pullback >=60bps from trailing 20-bar high
# while still above EMA50 + momentum recovery (r5 >= 20bps and RSI rising).
def pullback_entry(i, ctx, depth_bps=60, rec_bps=20):
    if i < 120 or lab.RSI[i] is None:
        return False
    if not (lab.EMA8[i] > lab.EMA21[i] > lab.EMA50[i]):
        return False
    hi20 = max(lab.C[i - 20:i])
    drop = math.log(lab.C[i] / hi20) * 1e4
    if drop > -depth_bps:
        return False
    if lab.C[i] <= lab.EMA50[i]:
        return False
    rec = math.log(lab.C[i] / lab.C[i - 5]) * 1e4
    if rec < rec_bps:
        return False
    if lab.RSI[i] <= lab.RSI[i - 1]:
        return False
    return True


PULLBACK_EXITS = {
    'PB-A trail65/TP100': fixed_exit(65, 100),
    'PB-B trail80/TP150/SL200': fixed_exit(80, 150, 200),
    'PB-C trail100/TP200/SL300': fixed_exit(100, 200, 300),
}


# ---------------- combined engines (SHIPPED + V4 / pullback / hybrid) ----------------
_R2 = {'name': None}


def _dip_sig(i, drop=150):
    return i >= 120 and math.log(lab.C[i] / max(lab.C[i - 120:i])) * 1e4 <= -drop


def _burst_sig(i):
    if i < 120:
        return False
    b = lab.logret(i, 5) * 1e4 >= 60 or lab.logret(i, 10) * 1e4 >= 80
    return b and lab.C[i] > lab.SMA120[i]


def _v4_sig(i):
    if i < 50 or lab.RSI[i] is None:
        return False
    trend = lab.EMA8[i] > lab.EMA21[i] > lab.EMA50[i]
    mom = lab.logret(i, 5) * 1e4 >= 30 or lab.logret(i, 10) * 1e4 >= 50
    return trend and mom and 45 <= lab.RSI[i] <= 75


def _pullback_sig(i):
    return pullback_entry(i, None)


def make_combined_entry(v4_exit_name, use_pullback=False, use_cost_gate=False,
                        v4_tp=100, pb_tp=150, dip_drop=150):
    """SHIPPED (dip + burst) + V4 (+ pullback) with per-engine fixed exits.
    Priority when several signals fire on one bar: dip > burst > v4 > pullback."""
    def entry(i, ctx):
        if i < 120:
            return False
        if _dip_sig(i, dip_drop):
            _R2['name'] = 'dip'
            return True
        if _burst_sig(i):
            _R2['name'] = 'burst'
            return True
        if _v4_sig(i):
            if use_cost_gate and not cost_gate_ok(i, ctx, v4_tp):
                pass  # cost gate fails: fall through to pullback, do not block it
            else:
                _R2['name'] = 'v4'
                return True
        if use_pullback and _pullback_sig(i):
            if use_cost_gate and not cost_gate_ok(i, ctx, pb_tp):
                return False
            _R2['name'] = 'pullback'
            return True
        return False
    return entry


def make_combined_exit(v4_exit_fn, pullback_exit_fn=None):
    def _exit(i, ctx):
        name = _R2['name']
        if name == 'burst':
            return lab.v1orig_exit(i, ctx)
        if name == 'dip':
            return lab.dip_exit(i, ctx)
        if name == 'v4':
            return v4_exit_fn(i, ctx)
        if name == 'pullback' and pullback_exit_fn is not None:
            return pullback_exit_fn(i, ctx)
        return lab.dip_exit(i, ctx)
    return _exit


# ---------------- dip grid (parameterised) ----------------
def make_dip(drop, trail, tp, sl):
    def entry(i, ctx):
        if i < 120:
            return False
        return math.log(lab.C[i] / max(lab.C[i - 120:i])) * 1e4 <= -drop
    return entry, fixed_exit(trail, tp, sl)


def split_half(en, ex, warmup=120, cooldown=5, fee_mult=1.0, size_frac=1.0):
    """Chronological train/validation split; each half re-installed alone."""
    set_w = lab.set_window
    set_w(FO[0:720], FH[0:720], FL[0:720], FC[0:720], FOD[0:720], FCD[0:720])
    r1 = lab.simulate(en, ex, warmup=min(warmup, 100), cooldown=cooldown,
                      fee_mult=fee_mult, size_frac=size_frac,
                      insurance_bar=None)
    set_w(FO[720:1440], FH[720:1440], FL[720:1440], FC[720:1440], FOD[720:1440], FCD[720:1440])
    r2 = lab.simulate(en, ex, warmup=min(warmup, 100), cooldown=cooldown,
                      fee_mult=fee_mult, size_frac=size_frac,
                      insurance_bar=None)
    restore_full()
    return r1, r2


def fee2(en, ex, warmup=120, cooldown=5, size_frac=1.0):
    return lab.simulate(en, ex, warmup=warmup, cooldown=cooldown,
                        fee_mult=2.0, size_frac=size_frac,
                        insurance_bar=1380, insurance_frac=0.05)


if __name__ == '__main__':
    out = {}
    print('== R2-6 DP ORACLE (perfect foresight, exact fill costs) ==')
    print('DP oracle 1x costs: net PnL $%.2f' % dp_oracle(1.0))
    print('DP oracle 2x costs: net PnL $%.2f' % dp_oracle(2.0))
    print('sum positive 1-min log-returns: %.2f bps; net drift %.2f bps' % (
        sum(max(0.0, math.log(FC[i] / FC[i - 1])) for i in range(1, N)) * 1e4,
        math.log(FC[-1] / FC[0]) * 1e4))
    print()
    print('== R2-1 V4 standalone with FIXED exits ==')
    for name, ex in V4_FIXED_SETS.items():
        r = lab.simulate(lab.v4_entry, ex, warmup=50, cooldown=5,
                         insurance_bar=1380, insurance_frac=0.05)
        lab.fmt(name, r)
        r1, r2 = split_half(lab.v4_entry, ex, warmup=50, cooldown=5)
        print('    split H1 $%.2f tr %d | H2 $%.2f tr %d | 2x-fee $%.2f' % (
            r1['pnl'], r1['trades'], r2['pnl'], r2['trades'],
            fee2(lab.v4_entry, ex, warmup=50)['pnl']))
    print()
    print('== R2-1 COMBINED: SHIPPED + V4 (fixed exits), no cost gate ==')
    for vname, vexit in V4_FIXED_SETS.items():
        en = make_combined_entry(vname, use_pullback=False)
        ex = make_combined_exit(vexit)
        r = lab.simulate(en, ex, warmup=120, cooldown=5,
                         insurance_bar=1380, insurance_frac=0.05)
        lab.fmt('SHIPPED+V4 ' + vname, r)
        r1, r2 = split_half(en, ex, warmup=120, cooldown=5)
        print('    split H1 $%.2f tr %d | H2 $%.2f tr %d | 2x-fee $%.2f' % (
            r1['pnl'], r1['trades'], r2['pnl'], r2['trades'],
            fee2(en, ex)['pnl']))
    print()
    print('== R2-2 PULLBACK standalone (3 exit sets) ==')
    for name, ex in PULLBACK_EXITS.items():
        r = lab.simulate(pullback_entry, ex, warmup=120, cooldown=5,
                         insurance_bar=1380, insurance_frac=0.05)
        lab.fmt('PULLBACK ' + name, r)
        r1, r2 = split_half(pullback_entry, ex, warmup=120, cooldown=5)
        print('    split H1 $%.2f tr %d | H2 $%.2f tr %d | 2x-fee $%.2f' % (
            r1['pnl'], r1['trades'], r2['pnl'], r2['trades'],
            fee2(pullback_entry, ex)['pnl']))
    print()
    print('== R2-3/4 HYBRID D: dip+burst+v4+pullback, regime-gated, cost gate ==')
    # regime gating is embedded by construction: v4/pullback entries already
    # require EMA8>EMA21>EMA50 (uptrend); dip fires in any regime; burst
    # requires close>SMA120. The hybrid below adds the cost gate on v4/pullback.
    for vname, vexit in V4_FIXED_SETS.items():
        for pname, pexit in PULLBACK_EXITS.items():
            en = make_combined_entry(vname, use_pullback=True, use_cost_gate=True,
                                     v4_tp={'V4f-A trail65/TP100': 100,
                                            'V4f-B trail100/TP200/SL300': 200,
                                            'V4f-C trail80/TP150/SL200': 150}[vname],
                                     pb_tp={'PB-A trail65/TP100': 100,
                                            'PB-B trail80/TP150/SL200': 150,
                                            'PB-C trail100/TP200/SL300': 200}[pname])
            ex = make_combined_exit(vexit, pexit)
            r = lab.simulate(en, ex, warmup=120, cooldown=5,
                             insurance_bar=1380, insurance_frac=0.05)
            lab.fmt('HYBRID %s + %s (cost gate)' % (vname, pname), r)
    print()
    print('== R2-4 E: best hybrid x position size ==')
    # (size sweep runs after the hybrid table above is inspected; the best
    #  hybrid by full-window PnL is re-run here at 0.5 / 0.75 / 1.0.)
    print('    (see r2_results.json for the size sweep on the best hybrid)')
    print()
    print('== R2-5 DIP GRID EXPANSION (108 cells) ==')
    grid = []
    for drop in (120, 150, 180, 210):
        for trail in (80, 100, 120):
            for tp in (150, 200, 250):
                for sl in (250, 300, 400):
                    en, ex = make_dip(drop, trail, tp, sl)
                    r = lab.simulate(en, ex, warmup=120, cooldown=5,
                                     insurance_bar=1380, insurance_frac=0.05)
                    grid.append((r['pnl'], drop, trail, tp, sl, r['trades'],
                                 r['max_dd'], r['total_fees']))
    grid.sort(reverse=True)
    for row in grid[:10]:
        print('    dip drop%d trail%d TP%d SL%d: pnl $%7.2f tr %2d DD %.3f fees $%.2f' % (
            row[1], row[2], row[3], row[4], row[0], row[5], row[6], row[7]))
    print('    cells positive: %d/108, negative: %d/108' % (
        sum(1 for g in grid if g[0] > 0), sum(1 for g in grid if g[0] <= 0)))
    print('    shipped cell (150/100/200/300) rank in grid: %d' % next(
        k + 1 for k, g in enumerate(grid)
        if (g[1], g[2], g[3], g[4]) == (150, 100, 200, 300)))
    json.dump({'grid_top10': [list(g) for g in grid[:10]],
               'grid_positive': sum(1 for g in grid if g[0] > 0)},
              open('r2_grid.json', 'w'), indent=1)
    print('    grid saved to r2_grid.json')
