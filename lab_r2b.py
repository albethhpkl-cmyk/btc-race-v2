"""BTC Race v2 — Round 2 part B: decisive tests.

1. PARTIAL-SIZE DP ORACLE: perfect-foresight upper bound allowing ANY
   position size (qty grid), exact fill costs. Decides whether the
   dev-top $92.41 is achievable under the verified fill model at all.
2. V4f-C trade log: why SHIPPED+V4 == SHIPPED on the dev window.
3. COMBINED with dip drop=180 (grid best) vs SHIPPED drop=150:
   full + split-half + 2x fee, against the round-2 selection rule.
4. Dip best-cell dims: cooldown {0,5,10} x size {0.5,0.75,1.0}.
5. E: size sweep on the combined (hybrid == shipped on dev) entry.
6. Regime distribution (regime5) over the dev window.
"""
import math

import lab
import lab_r2

FO, FH, FL, FC, FOD, FCD = lab.O, lab.H, lab.L, lab.C, lab.OD, lab.CD
N = len(FC)


def dp_oracle_partial(step_btc=0.001, fee_mult=1.0):
    """Perfect-foresight bound with ANY position size.
    State: qty grid (BTC). At each open, switch to any qty level paying
    the EXACT fill costs (fee 4bps, slip 2bps, constant-product impact
    vs the bar's open depth). Returns (net PnL, n_switches)."""
    O, C, OD, CD = lab.O, lab.C, lab.OD, lab.CD
    fee = 0.0004 * fee_mult
    slip = 0.0002 * fee_mult
    max_qty = 1000.0 / 60000.0  # ~$1000 of BTC at ~$60k
    levels = []
    q = 0.0
    while q <= max_qty + 1e-12:
        levels.append(round(q, 9))
        q += step_btc
    L = len(levels)

    def buy_cash_needed(dq, op, dep):
        """Cash needed to buy dq BTC at open op (exact fill inversion)."""
        if dq <= 0:
            return 0.0
        x = dq * op * (1 + slip) / (1 - dq * op * (1 + slip) / dep)
        return x / (1 - fee)

    def sell_proceeds(dq, op, dep):
        """Net cash from selling dq BTC at open op (exact fill)."""
        if dq <= 0:
            return 0.0
        val = dq * op
        a = val * 1e6
        fp = op * (1 - slip) / (1 + a / dep)
        return dq * fp * (1 - fee)

    NEG = -1e18
    cash = [NEG] * L
    cash[0] = 1000.0
    switches = [0] * L
    for i in range(N):
        op, dep = O[i], OD[i]
        new_cash = [NEG] * L
        new_sw = [0] * L
        for b in range(L):
            qb = levels[b]
            best = NEG
            best_sw = 0
            for a in range(L):
                if cash[a] == NEG:
                    continue
                qa = levels[a]
                if qb >= qa:
                    need = buy_cash_needed(qb - qa, op, dep)
                    c = cash[a] - need
                    sw = switches[a] + (1 if qb > qa else 0)
                else:
                    c = cash[a] + sell_proceeds(qa - qb, op, dep)
                    sw = switches[a] + 1
                if c > best:
                    best = c
                    best_sw = sw
            new_cash[b] = best
            new_sw[b] = best_sw
        cash, switches = new_cash, new_sw
    best = NEG
    best_sw = 0
    for a in range(L):
        if cash[a] == NEG:
            continue
        c = cash[a] + sell_proceeds(levels[a], C[-1], CD[-1])
        if c > best:
            best = c
            best_sw = switches[a]
    return best - 1000.0, best_sw


if __name__ == '__main__':
    print('== B1 PARTIAL-SIZE DP ORACLE (any size, exact costs) ==')
    pnl, sw = dp_oracle_partial(0.001)
    print('DP oracle partial-size (0.001 BTC steps): net PnL $%.2f, switches %d' % (pnl, sw))
    pnl2, sw2 = dp_oracle_partial(0.0005)
    print('DP oracle partial-size (0.0005 BTC steps): net PnL $%.2f, switches %d' % (pnl2, sw2))
    print('DP oracle bang-bang (lab_r2, full-size only): $63.65; top entry: $92.41')
    print()
    print('== B2 V4f-C standalone trade log (why combined == shipped) ==')
    r = lab.simulate(lab.v4_entry, lab_r2.V4_FIXED_SETS['V4f-C trail80/TP150/SL200'],
                     warmup=50, cooldown=5, insurance_bar=1380, insurance_frac=0.05)
    print('V4f-C log:', r['log'])
    print('V4 signals (bars where _v4_sig fires):',
          [i for i in range(120, N) if lab_r2._v4_sig(i)][:20])
    print('dip position holding bars 121-508 (shipped); burst tradeable bar: 400')
    print('pullback signals:', [i for i in range(120, N) if lab_r2._pullback_sig(i)])
    print()
    print('== B3 COMBINED dip-drop180 vs SHIPPED dip-drop150 ==')
    for drop in (150, 180):
        en = lab_r2.make_combined_entry('V4f-C trail80/TP150/SL200',
                                        use_pullback=False, dip_drop=drop)
        ex = lab_r2.make_combined_exit(lab_r2.V4_FIXED_SETS['V4f-C trail80/TP150/SL200'])
        r = lab.simulate(en, ex, warmup=120, cooldown=5,
                         insurance_bar=1380, insurance_frac=0.05)
        lab.fmt('COMBINED dip-drop%d + burst + V4f-C' % drop, r)
        print('    log:', r['log'])
        r1, r2 = lab_r2.split_half(en, ex, warmup=120, cooldown=5)
        print('    split H1 $%.2f tr %d | H2 $%.2f tr %d | 2x-fee $%.2f' % (
            r1['pnl'], r1['trades'], r2['pnl'], r2['trades'],
            lab_r2.fee2(en, ex)['pnl']))
    print()
    print('== B4 DIP best-cell dims (drop180/trail100/TP200/SL300) ==')
    for cd in (0, 5, 10):
        en, ex = lab_r2.make_dip(180, 100, 200, 300)
        r = lab.simulate(en, ex, warmup=120, cooldown=cd,
                         insurance_bar=1380, insurance_frac=0.05)
        print('    cooldown %2d: pnl $%7.2f tr %d' % (cd, r['pnl'], r['trades']))
    for sz in (0.5, 0.75, 1.0):
        en, ex = lab_r2.make_dip(180, 100, 200, 300)
        r = lab.simulate(en, ex, warmup=120, cooldown=5, size_frac=sz,
                         insurance_bar=1380, insurance_frac=0.05)
        print('    size %.2f: pnl $%7.2f tr %d' % (sz, r['pnl'], r['trades']))
    print()
    print('== B5 E: size sweep on COMBINED (hybrid == shipped on dev) ==')
    for sz in (0.5, 0.75, 1.0):
        en = lab_r2.make_combined_entry('V4f-C trail80/TP150/SL200',
                                        use_pullback=True, use_cost_gate=True,
                                        v4_tp=150, pb_tp=150, dip_drop=150)
        ex = lab_r2.make_combined_exit(
            lab_r2.V4_FIXED_SETS['V4f-C trail80/TP150/SL200'],
            lab_r2.PULLBACK_EXITS['PB-B trail80/TP150/SL200'])
        r = lab.simulate(en, ex, warmup=120, cooldown=5, size_frac=sz,
                         insurance_bar=1380, insurance_frac=0.05)
        print('    hybrid size %.2f: pnl $%7.2f tr %d DD %.3f fees $%.2f' % (
            sz, r['pnl'], r['trades'], r['max_dd'], r['total_fees']))
    print()
    print('== B6 REGIME distribution (regime5, dev window) ==')
    from collections import Counter
    print(Counter(lab_r2.regime5(i) for i in range(120, N)))
    print('RT cost at median depth ($844k, $1000): %.1f bps; 2x gate: %.1f bps' % (
        lab_r2.rt_cost_bps(500, 1000.0), 2 * lab_r2.rt_cost_bps(500, 1000.0)))
