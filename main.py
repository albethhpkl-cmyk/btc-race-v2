"""BTC Race v2 — deep-dip swing + momentum-burst bot (agent-fun/bars-replay/v1).

Strategy (validated on the frozen dev window with the lab's exact fill model,
lab.py in this workspace — NOT on live money; this is a paper-money replay):
  Engine D (primary) — deep-dip swing: buy 100% of equity when the close is
    >=180 bps below the trailing 120-bar high. Exit: trailing stop 100 bps
    below the peak, or take-profit +200 bps, or stop-loss -300 bps, all
    measured from the entry decision's close (log returns).
  Engine B (secondary) — momentum burst, the v1 rule, validated standalone
    at +$6.47 on the dev window: buy 100% when the 5-min return is >=60 bps
    or the 10-min return is >=80 bps AND the close is above SMA120.
    Exit: trailing stop 65 bps below the peak, or take-profit +100 bps.
  One open position at most; 5-bar cooldown after any exit (no duplicate
  entries on the same signal); insurance buy of 5% of equity at bar 1380
  if nothing ever traded (keeps the >=1-trade guardrail).

What was tested and REJECTED on this window (kept in lab.py, not shipped):
  EMA 8/21 crossover, Momentum+RSI, Breakout+volume-proxy, EMA+Momentum,
  and the 5-engine adaptive combiner all lost money (-$15.80 to -$42.42);
  ATR-adaptive exits underperformed fixed wide exits by $5.75; a unified
  wide exit turned the burst engine's +$6.47 into -$1.13. Exits are
  therefore per-engine and fixed, as validated.

Determinism: standard library only, no network, no wall clock, no random,
no files. Identical bars give byte-identical action logs (verified by
running the official grader twice — see REPORT.md).
"""

import math
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "vendor"))
import makefun_bars

# --- validated parameters (bps; see lab.py plateau grid + lab_r2.py round-2 grid) ---
DIP_DROP_BPS = 180       # close >=180 bps below trailing 120-bar high
                         # (round 2: 180 beats 150 by +$0.90 — it skips one
                         # marginal dip trade at bar 1437 that lost money;
                         # 9 grid cells tie at +$17.55, plateau not knife-edge)
DIP_TRAIL_BPS = 100      # trailing stop below peak
DIP_TP_BPS = 200         # take profit vs entry close
DIP_SL_BPS = 300         # stop loss vs entry close
BURST_R5_BPS = 60        # 5-min return
BURST_R10_BPS = 80       # 10-min return
BURST_TRAIL_BPS = 65
BURST_TP_BPS = 100
SMA_BARS = 120
COOLDOWN_BARS = 5
INSURANCE_BAR = 1380    # 0-based bar index in the scored window
INSURANCE_FRAC_BPS = 500  # 5% of equity
MAX_SLIPPAGE_BPS = 100
MIN_NOTIONAL_QUOTE_UNITS = 1_000_000  # 1 USDC


class Bot:
    def __init__(self, symbol):
        self.symbol = symbol
        self.closes = []          # raw close ints, oldest first
        self.n_bars = 0           # fresh bars seen (incl. warm-up bars)
        self.has_fill = False
        self.holding = False      # fill-confirmed open position
        self.pending_buy = None   # (engine, entry_close_raw, client_id)
        self.engine = None        # 'dip' | 'burst' | 'insurance'
        self.entry_close = None   # raw close at the entry decision bar
        self.peak = None          # highest close since entry (prev bar's)
        self.cooldown_until = -1  # bar index; entries blocked while n < this

    # -- indicator helpers (floats on raw ints; ratios are scale-free) --
    def _log_bps(self, now, then):
        return math.log(now / then) * 10000.0

    def _sma120(self):
        return sum(self.closes[-SMA_BARS:]) / float(SMA_BARS)

    def _dip(self):
        """Close >=150 bps below the trailing 120-bar high (excl. current)."""
        if len(self.closes) < SMA_BARS + 1:
            return False
        hi = max(self.closes[-SMA_BARS - 1:-1])
        return self._log_bps(self.closes[-1], hi) <= -DIP_DROP_BPS

    def _burst(self):
        """5-min >=60 bps or 10-min >=80 bps, close above SMA120."""
        if len(self.closes) < SMA_BARS + 1:
            return False
        c = self.closes[-1]
        r5 = self._log_bps(c, self.closes[-6])
        r10 = self._log_bps(c, self.closes[-11])
        return (r5 >= BURST_R5_BPS or r10 >= BURST_R10_BPS) and c > self._sma120()

    def _exit(self):
        """Exit decision for the open position, using the peak as of the
        PREVIOUS bar (exactly like the lab simulator's ctx)."""
        c = self.closes[-1]
        if self.engine == 'burst':
            if self.peak is not None and self._log_bps(c, self.peak) <= -BURST_TRAIL_BPS:
                return True
            return self._log_bps(c, self.entry_close) >= BURST_TP_BPS
        # dip / insurance: wide trailing stop, TP, SL
        if self.peak is not None and self._log_bps(c, self.peak) <= -DIP_TRAIL_BPS:
            return True
        if self._log_bps(c, self.entry_close) >= DIP_TP_BPS:
            return True
        if self._log_bps(c, self.entry_close) <= -DIP_SL_BPS:
            return True
        return False

    def on_batch(self, state, batch):
        # Resolve the previous reply's fills first.
        for f in batch.get('fills', []):
            if f.get('symbol') != self.symbol:
                continue
            if f.get('status') == 'filled':
                self.has_fill = True
                if f.get('side') == 'buy' and self.pending_buy is not None:
                    engine, entry_close, _cid = self.pending_buy
                    self.pending_buy = None
                    self.holding = True
                    self.engine = engine
                    self.entry_close = entry_close
                    self.peak = None
                elif f.get('side') == 'sell':
                    self.holding = False
                    self.engine = None
                    self.entry_close = None
                    self.peak = None
            elif f.get('status') == 'rejected' and self.pending_buy is not None:
                if f.get('client_id') == self.pending_buy[2]:
                    self.pending_buy = None
        # A position the account shows but we do not track cannot happen in
        # normal flow; if it does, drop stale entry state (never trade blind).
        held = state.positions.get(self.symbol)
        if (held is None or held.qty <= 0) and self.holding:
            # Sell filled but the fill record was missed: treat as flat.
            # (Only reachable if the harness reports fills out of order.)
            if self.pending_buy is None:
                self.holding = False
                self.engine = None
                self.entry_close = None
                self.peak = None
        # Fresh bar for our symbol?
        bar = None
        for b in batch.get('bars', []):
            if b.get('symbol') == self.symbol:
                bar = b
                break
        if bar is None:
            return []
        close = int(bar['c'])
        self.closes.append(close)
        self.n_bars += 1
        idx = self.n_bars - 1  # 0-based index in the scored window
        if state.warming_up:
            return []
        if self.pending_buy is not None:
            return []  # buy in flight; its fill lands on the next batch
        if self.holding:
            # Exit check uses the peak as of the previous bar (lab order).
            if self._exit():
                qty = held.qty if held is not None else 0
                if qty > 0:
                    self.cooldown_until = idx + COOLDOWN_BARS
                    return [{'side': 'sell', 'symbol': self.symbol, 'qty': qty,
                             'max_slippage_bps': MAX_SLIPPAGE_BPS,
                             'client_id': 's%d' % idx}]
            # Update the peak with this bar's close (for later bars).
            self.peak = close if self.peak is None else max(self.peak, close)
            return []
        # Flat: entries.
        if idx < SMA_BARS or idx < self.cooldown_until:
            return []
        if not self.has_fill and idx >= INSURANCE_BAR:
            notional = state.equity * INSURANCE_FRAC_BPS // 10000
            if notional >= MIN_NOTIONAL_QUOTE_UNITS and state.cash >= notional:
                cid = 'i%d' % idx
                self.pending_buy = ('insurance', close, cid)
                return [{'side': 'buy', 'symbol': self.symbol,
                         'notional_quote_units': notional,
                         'max_slippage_bps': MAX_SLIPPAGE_BPS, 'client_id': cid}]
            return []
        engine = None
        if self._dip():
            engine = 'dip'
        elif self._burst():
            engine = 'burst'
        if engine is None:
            return []
        notional = state.cash
        if notional < MIN_NOTIONAL_QUOTE_UNITS:
            return []
        cid = 'b%d' % idx
        self.pending_buy = (engine, close, cid)
        return [{'side': 'buy', 'symbol': self.symbol,
                 'notional_quote_units': notional,
                 'max_slippage_bps': MAX_SLIPPAGE_BPS, 'client_id': cid}]


def on_hello(state):
    pass


def main():
    bot = None

    def _on_hello(state):
        nonlocal bot
        symbols = [s['symbol'] for s in state.hello['symbols']]
        bot = Bot(symbols[0])

    def _on_batch(state, batch):
        return bot.on_batch(state, batch)

    makefun_bars.run(_on_batch, on_hello=_on_hello)


if __name__ == '__main__':
    main()
