"""Local protocol replay for btc-race-v2/main.py (NOT the official grader).

Why this exists: the official `grade-local` needs Docker for a Python bot
(process driver runs node22 only) and this VM has no Docker. This driver
speaks the exact agent-fun/bars-replay/v1 protocol to main.py as a
subprocess (via the official vendored shim) and prices fills with the SAME
fill model as lab.py — the model that reproduced the v1 submission's server
dev grade (+$6.47) to the cent. Before any real submission, run the official
`grade-local --driver docker` from the kit directory and confirm it agrees.

Usage: python3 validate_local.py [--runs 2]
Prints: net PnL, return, trades, round trips, win rate, profit factor,
max DD, total fees, per-hour-block PnL, trade log, and whether the action
logs of the two runs are byte-identical.
"""

import gzip
import json
import math
import os
import subprocess
import sys

KIT = os.path.expanduser(
    '~/workspace/makefun/btc-race-20261118-1444/'
    'btc-race-24h-20261118-1444-kit')
DATA = os.path.join(KIT, 'dataset/bars/CBBTC.ndjson.gz')
BOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'main.py')
SYMBOL = 'CBBTC'
PRICE_SCALE = 5
QTY_SCALE = 8
QUOTE_SCALE = 6
START_CASH_USDC = 1000.0
FEE_BPS = 0.0004
SLIP_BPS = 0.0002


def load_bars(path=DATA):
    bars = []
    with gzip.open(path, 'rt') as f:
        for line in f:
            bars.append(json.loads(line))
    return bars


def run_once(bars):
    env = dict(os.environ)
    env['PYTHONHASHSEED'] = '0'
    proc = subprocess.Popen(
        [sys.executable, '-P', '-s', BOT],
        stdin=subprocess.PIPE, stdout=subprocess.PIPE,
        stderr=subprocess.PIPE, env=env)
    log_lines = []

    def send(msg):
        line = json.dumps(msg, separators=(',', ':')).encode()
        proc.stdin.write(line + b'\n')
        proc.stdin.flush()

    def recv():
        line = proc.stdout.readline()
        log_lines.append(line)
        return json.loads(line)

    hello = {
        'type': 'hello', 'protocol': 'agent-fun/bars-replay/v1',
        'seed': '12345', 'warmup_bars': 0,
        'capital': {'quote_units': str(int(START_CASH_USDC * 10 ** QUOTE_SCALE)),
                    'quote_scale': QUOTE_SCALE},
        'symbols': [{'symbol': SYMBOL,
                     'mint': 'cbbtcf3aa214zXHbiAZQwf4122FBYbraNdFqgw4iMij',
                     'price_scale': PRICE_SCALE, 'qty_scale': QTY_SCALE}],
        'caps': {'max_open_positions': 1, 'max_orders_per_bar': 16,
                 'max_weight_bps': 10000},
    }
    send(hello)

    cash = START_CASH_USDC
    qty = 0.0
    cost = 0.0
    pending = None          # (side, amount) — amount: notional USDC (buy) / qty (sell)
    trades = 0
    total_fees = 0.0
    peak_eq = START_CASH_USDC
    max_dd = 0.0
    block_pnl = [0.0] * 24
    prev_eq = START_CASH_USDC
    trade_log = []

    def account(close):
        eq = cash + qty * close
        pos = []
        if qty > 0:
            pos.append({'symbol': SYMBOL,
                        'qty': str(int(round(qty * 10 ** QTY_SCALE))),
                        'cost_quote_units': str(int(round(cost * 10 ** QUOTE_SCALE)))})
        return {'cash_quote_units': str(int(round(cash * 10 ** QUOTE_SCALE))),
                'equity_quote_units': str(int(round(eq * 10 ** QUOTE_SCALE))),
                'positions': pos}

    def apply_fill(i):
        nonlocal cash, qty, cost, trades, total_fees
        if pending is None:
            return None
        side, amt, _cid = pending
        bar = bars[i]
        op = int(bar['o']) / 10 ** PRICE_SCALE
        dep = int(bar['o_depth'][0])
        prev = int(bars[i - 1]['c']) / 10 ** PRICE_SCALE if i > 0 else op
        if side == 'buy':
            fee = amt * FEE_BPS
            a = (amt - fee) * 1e6
            fp = op * (1 + SLIP_BPS) * (1 + a / dep)
            if fp > prev * 1.01:
                return {'client_id': pending[2], 'symbol': SYMBOL,
                        'side': 'buy', 'status': 'rejected', 'reason': 'max_slippage'}
            q = (amt - fee) / fp
            cash -= amt
            qty += q
            cost += amt
            trades += 1
            total_fees += fee
            trade_log.append(('BUY', i, round(fp, 2)))
            return {'client_id': pending[2], 'symbol': SYMBOL,
                    'side': 'buy', 'status': 'filled'}
        val = amt * op
        a = val * 1e6
        fp = op * (1 - SLIP_BPS) / (1 + a / dep)
        if fp < prev * 0.99:
            return {'client_id': pending[2], 'symbol': SYMBOL,
                    'side': 'sell', 'status': 'rejected', 'reason': 'max_slippage'}
        proceeds = amt * fp
        fee = proceeds * FEE_BPS
        cash += proceeds - fee
        qty -= amt
        cost = 0.0
        trades += 1
        total_fees += fee
        trade_log.append(('SELL', i, round(fp, 2)))
        return {'client_id': pending[2], 'symbol': SYMBOL,
                'side': 'sell', 'status': 'filled'}

    n = len(bars)
    for i in range(n):
        bar = bars[i]
        fills = []
        f = apply_fill(i)
        if f is not None:
            fills.append(f)
        pending = None
        close = int(bar['c']) / 10 ** PRICE_SCALE
        eq = cash + qty * close
        block_pnl[i // 60] += eq - prev_eq
        prev_eq = eq
        if eq > peak_eq:
            peak_eq = eq
        dd = (peak_eq - eq) / START_CASH_USDC
        if dd > max_dd:
            max_dd = dd
        batch = {'type': 'batch', 'seq': i, 't': int(bar['t']),
                 'bars': [{'symbol': SYMBOL, 't': int(bar['t']),
                           'o': str(bar['o']), 'h': str(bar['h']),
                           'l': str(bar['l']), 'c': str(bar['c']),
                           'v': None,
                           'o_depth': [str(d) for d in bar['o_depth']],
                           'c_depth': [str(d) for d in bar['c_depth']]}],
                 'fills': fills, 'account': account(close)}
        send(batch)
        reply = recv()
        assert reply['type'] == 'reply' and reply['seq'] == i, reply
        orders = reply.get('orders', [])
        assert len(orders) <= 16
        for o in orders:
            if o['side'] == 'buy':
                pending = ('buy', int(o['notional_quote_units']) / 10 ** QUOTE_SCALE,
                           o['client_id'])
            else:
                pending = ('sell', int(o['qty']) / 10 ** QTY_SCALE, o['client_id'])
    # End flatten at the last close against its close depth.
    if qty > 0:
        close = int(bars[-1]['c']) / 10 ** PRICE_SCALE
        dep = int(bars[-1]['c_depth'][0])
        val = qty * close
        fp = close * (1 - SLIP_BPS) / (1 + val * 1e6 / dep)
        proceeds = qty * fp
        fee = proceeds * FEE_BPS
        cash += proceeds - fee
        total_fees += fee
        qty = 0.0
        trade_log.append(('FLATTEN', n - 1, round(fp, 2)))
    send({'type': 'done', 'seq': n, 'account': account(close)})
    proc.stdin.close()
    err = proc.stderr.read().decode()
    proc.wait()
    if proc.returncode != 0:
        raise RuntimeError('bot exited %d: %s' % (proc.returncode, err[:2000]))
    if err.strip():
        print('bot stderr:', err[:2000], file=sys.stderr)
    pnl = cash - START_CASH_USDC
    buys = [x for x in trade_log if x[0] == 'BUY']
    sells = [x for x in trade_log if x[0] in ('SELL', 'FLATTEN')]
    rts = min(len(buys), len(sells))
    rt_rets = [math.log(sells[k][2] / buys[k][2]) * 1e4 for k in range(rts)]
    wins = sum(1 for r in rt_rets if r > 0)
    gw = sum(r for r in rt_rets if r > 0)
    gl = sum(-r for r in rt_rets if r <= 0)
    pf = (gw / gl) if gl > 0 else (float('inf') if gw > 0 else 0.0)
    return dict(pnl=pnl, ret=pnl / START_CASH_USDC, trades=trades,
                roundtrips=rts, win_rate=(wins / rts if rts else 0.0),
                profit_factor=pf, max_dd=max_dd, total_fees=total_fees,
                block_pnl=block_pnl, trade_log=trade_log,
                action_log=b''.join(log_lines))


def main():
    runs = int(sys.argv[sys.argv.index('--runs') + 1]) if '--runs' in sys.argv else 2
    bars = load_bars()
    print('bars:', len(bars))
    results = [run_once(bars) for _ in range(runs)]
    r = results[0]
    print('net PnL        $%7.2f  return %+0.2f%%' % (r['pnl'], r['ret'] * 100))
    print('trades         %d  (round trips %d, win rate %.2f, PF %s)'
          % (r['trades'], r['roundtrips'], r['win_rate'],
             ('inf' if r['profit_factor'] == float('inf') else '%.2f' % r['profit_factor'])))
    print('max drawdown   %.2f%%' % (r['max_dd'] * 100))
    print('total fees     $%.2f' % r['total_fees'])
    print('trade log      %s' % (r['trade_log'],))
    print('per-hour-block %s' % (['%+.2f' % x for x in r['block_pnl']],))
    print('positive blocks %d/24' % sum(1 for x in r['block_pnl'] if x > 0))
    same = all(x['action_log'] == results[0]['action_log'] for x in results[1:])
    print('determinism    %d runs, action logs byte-identical: %s'
          % (runs, same))
    print('action log     %d bytes' % len(r['action_log']))


if __name__ == '__main__':
    main()
