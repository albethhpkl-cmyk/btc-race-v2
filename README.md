# BTC Race v2 — deep-dip swing + momentum-burst bot

Paper-money bot for the make.fun BTC Race (`agent-fun/bars-replay/v1`,
long-only CBBTC, $1,000 USDC start). **NOT submitted. Do not submit
without the user's explicit approval and without running the official
`grade-local` (Docker) first — see "Validation status" below.**

## Files

| File | What it is |
|---|---|
| `main.py` | The bot. Python 3.13, standard library only. |
| `vendor/makefun_bars.py` | Byte-identical copy of the kit's official Python shim. |
| `lab.py` | Backtest lab: exact fill model + all tested variants (V1–V5, baselines, DIP, COMBO, SHIPPED). |
| `lab_r2.py` | Round-2 lab: V4 fixed exits, pullback engine, hybrid D (regime filter + cost gate), dip-grid expansion (108 cells), DP oracle (bang-bang). |
| `lab_r2b.py` | Round-2 part B: partial-size DP oracle, V4/combined diagnostics, dip-180 adoption checks, size/cooldown dims, regime mix. |
| `r2_grid.json` | Top-10 cells of the 108-cell dip grid. |
| `validate_local.py` | Protocol replay driver: runs `main.py` as a subprocess over the frozen dev window through the official shim, twice, and compares action logs. |
| `REPORT.md` | Full audit report, official-rules summary, comparison table, honest recommendation. |
| `LICENSE` | MIT. |

## Strategy (shipped)

Two engines, one open position at most, 5-bar cooldown after any exit.

- **Engine D — deep-dip swing (primary).** Buy 100% of equity when the
  close is ≥180 bps below the trailing 120-bar high (round 2: 180 beats
  150 by +$0.90 — it skips one marginal dip trade at bar 1437 that lost
  money). Exit: trailing stop 100 bps below the peak, take-profit
  +200 bps, or stop-loss −300 bps (log returns vs the entry decision's close).
- **Engine B — momentum burst (secondary, the v1 rule).** Buy 100% when
  the 5-min return is ≥60 bps or the 10-min return is ≥80 bps AND the
  close is above SMA120. Exit: trailing stop 65 bps below the peak, or
  take-profit +100 bps.
- **Insurance.** If nothing ever traded by bar 1380, buy 5% of equity
  (keeps the ≥1-trade guardrail). Exits for an insurance position use
  the dip engine's wide exits.

## Every config change vs v1 — and why (all measured on the frozen dev window)

| Change | Reason | Test result |
|---|---|---|
| Added dip-swing engine (drop ≥150 bps from 120-bar high) | v1's burst fired on only 1 bar in the whole window; the window's one big move was a −2.8% drift with a deep early dip and a slow grind up — a dip-buyable shape, not a burst shape | DIP-only +$16.65 (1 completed round trip, BUY 121 → SELL 508, +182 bps) |
| Wide exits for the dip engine (trail 100 / TP 200 / SL 300 bps) | ATR ≈ 5 bps: a tight exit chops the swing to death; holds of ~100 bars are needed to ride the grind | Trail-only riders −$62 to −$157; TP-only scalpers negative; wide exits +$16.65 |
| Kept v1 burst engine + its own exits (trail 65 / TP 100) | Validated standalone at +$6.47; a unified wide exit turned it into −$1.13, so exits stay per-engine | Burst never fires while the dip position is open on dev; kept as second chance for a trending race window |
| Exits FIXED bps, not ATR-adaptive | ATR-adaptive exits (clamped to reproduce the fixed values at typical ATR) exited the dip swing early | COMBO ATR +$10.90 vs SHIPPED fixed +$16.65 (−$5.75) |
| 5-bar cooldown after any exit | Prevents duplicate entries on the same signal | Part of every lab run; no separate ablation, kept as a safety rail |
| Insurance 5% at bar 1380 (unchanged from v1) | Guardrail: ≥1 trade required to rank | Never triggered on dev (trades happened earlier) |
| 100% equity per entry (unchanged) | Round-trip cost is ~35 bps at live depth; the swing's gross (+182 bps) clears it with margin, and the 100% sizing is what was validated | Size sweep (round 2): 0.50 → +$9.37, 0.75 → +$13.61, 1.00 → +$17.55 — full size wins |
| Dip threshold 150 → 180 bps (round 2) | 108-cell grid: 9 cells tie at +$17.55 (drop 180, TP 200); the shipped 150-cell ranks 23rd; drop 180 also avoids a losing H2 dip trade | Combined +$17.55 (2 trades) vs +$16.65; H2 $0.00 vs −$0.83; 2x-fee $16.33 vs $14.22 — adopted, see REPORT.md §8.4 |

## What was tested and REJECTED (kept in `lab.py`, not shipped)

| Variant | Dev net PnL | Why it loses |
|---|---|---|
| V1 EMA 8/21 crossover | −$28.42 | 8 trades, win 0.25 — whipsaw in chop |
| V2 Momentum + RSI | −$15.80 | 6 trades, win 0.33 — momentum fades within bars |
| V3 Breakout + volume proxy | −$42.42 | 26 trades, win 0.00 — breakouts fail, fees $10.18 |
| V4 EMA + Momentum | +$1.99 | Marginal; not shipped (kept as a possible 3rd engine after fixed-exit validation) |
| V4 fixed exits (round 2) | +$12.24 best (trail80/TP150/SL200); +$1.22 / +$5.07 others | Best fixed V4, but 0 trades in H2; combined with SHIPPED it changes nothing (its signals fall inside the dip holding period) — NOT added, see REPORT.md §8.1 |
| Pullback continuation (round 2, NEW) | −$0.43 to −$0.64 | Zero signals in 1,440 bars; its only "trades" were the insurance buy — NOT added, see REPORT.md §8.2 |
| Hybrid D: dip+burst+V4+pullback, regime filter + cost gate (round 2) | +$16.65 (all 9 combos) | Identical to SHIPPED — neither new engine ever enters while flat — no change, see REPORT.md §8.3 |
| V5 Adaptive Multi-Strategy (summed score ≥70) | −$6.06 | Summed threshold vetoes the dip trade (dip scores 55 while trend/momentum point the other way) |
| V5 fixed (per-engine thresholds) | −$20.67 | Losing trades fire during uptrend stretches inside the grind-down; gating changes nothing (identical −$20.67) |
| Official baselines | buy-and-hold −$31.63; EMA-cross −$148.16; RSI-Bollinger −$39.91; momentum-24 −$23.87; hold-cash $0.00 | The dev window punishes trend-following |
| ATR-adaptive exits (COMBO) | +$10.90 | Exits the swing early (−$5.75 vs fixed) |

Volume confirmation as specified in the directive is **not** in the bot:
bars carry `v: null` (RULES.txt: "volume is null (pool state carries
none)"). The lab uses the documented price-based proxy (bar-range
expansion vs ATR + next-bar follow-through) only inside the rejected
V3 variant. No volume was invented anywhere.

## Results (frozen dev window, 1,440 bars, exact fill model)

| Bot | Net PnL | Return | Trades | Win | Max DD | Fees | PF |
|---|---|---|---|---|---|---|---|
| v1 submitted | +$6.47 | +0.65% | 2 | 1.00 | 0.64% | $0.80 | inf |
| **v2 SHIPPED** | **+$16.65** | **+1.67%** | **3** | **1.00*** | **0.76%** | **$1.62** | **inf** |
| **v2-r2 (current, drop 180)** | **+$17.55** | **+1.75%** | **2** | **1.00** | **0.76%** | **$0.81** | **inf** |
| v2 2x-fee test | +$14.22 | +1.42% | 3 | 1.00 | — | — | — |
| v2-r2 2x-fee test | +$16.33 | +1.63% | 2 | 1.00 | — | — | — |
| v2 split-half H1 / H2 | +$17.55 / −$0.83 | — | 2 / 1 | — | — | — | — |
| v2-r2 split-half H1 / H2 | +$17.55 / $0.00 | — | 2 / 0 | — | — | — | — |

\* 1 completed round trip (win); the 3rd trade is a BUY at bar 1437
flattened at window end for −$0.08. The protocol replay counts it as a
2nd round trip (win rate 0.50 there); the lab does not count the flatten
as a round trip.

Dip parameter plateau (round-2 grid, 108 cells: drop 120/150/180/210 ×
trail 80/100/120 × TP 150/200/250 × SL 250/300/400): **105/108
positive, top +$17.55 (9 cells tie: drop 180, TP 200)**. The shipped
150-cell ranks 23rd. This is a plateau, not a knife-edge — but the
+ $0.90 gain from 150 → 180 comes from skipping one marginal trade, so
treat it as a small refinement, not a breakthrough (REPORT.md §8.4).

## Validation status

- [x] Lab (`python3 lab.py`): SHIPPED v2 +$16.65, H1 +$17.55 / H2 −$0.83,
      2x-fee +$14.22.
- [x] Round-2 lab (`python3 lab_r2.py`, `python3 lab_r2b.py`): v2-r2
      (drop 180) +$17.55, H1 +$17.55 / H2 $0.00, 2x-fee +$16.33.
- [x] Protocol replay (`python3 validate_local.py --runs 2`) re-run after
      the drop-180 change: `main.py` through the official shim: **+$17.55,
      same trades as the lab (BUY 121 → SELL 508), 2 runs byte-identical
      action logs (56,689 bytes), exit 0, no protocol errors**, max DD
      0.76%, ≥1 qualifying trade.
- [ ] **Official `grade-local` NOT yet run.** It needs Docker for a
      Python bot (the process driver runs node22 only) and this VM has
      no Docker. Run from the kit directory before any submission:
      `node cli/makefun.mjs grade-local --kit . --bot <repo> --worktree`
      (default driver is Docker). The local replay uses the same fill
      model that reproduced v1's server dev grade (+$6.47) to the cent,
      but it is not the grader.
- [ ] Submission: **NOT submitted, NOT auto-submitted.** Awaiting the
      user's explicit approval (binding rule for this bot).

## How to run

```bash
python3 lab.py                    # full lab: baselines, V1-V5, DIP, COMBO, SHIPPED, split-half, 2x fee
python3 lab_r2.py                 # round 2: V4-fixed, pullback, hybrid D, dip grid, DP oracle
python3 lab_r2b.py                # round 2 part B: partial-size DP oracle, drop-180 checks
python3 validate_local.py --runs 2   # protocol replay of main.py, determinism check
```

## Known weaknesses (honest)

1. The dev result rests on **one swing trade** (BUY 121 → SELL 508).
   The race window is unseen and may contain no ≥180 bps dip — then
   only the burst engine or the 5% insurance can qualify the entry.
2. H2 (validation half) is $0.00 for v2-r2 (−$0.83 for v2): the dip edge
   does not repeat in the second half. This is a one-window result, not
   a proven edge.
3. **$90 PnL is NOT promised.** Measured best dev result is +$17.55;
   $90 is approximately the dev-top level (top entry $92.40, 388
   trades). Round 2 proved $92.40 is below the perfect-foresight bound
   with any size (+$108–111), so it is achievable in principle — but
   only with near-perfect foresight, i.e. heavy dev-window overfitting
   that does not transfer to the unseen race window (REPORT.md §8.6).
4. Full-size entries pay ~35 bps per round trip at live depth
   (median o_depth ~$844k); a shallower race window costs more.
5. `main.py` trusts the harness's account state; if a buy is rejected
   (e.g. slippage cap) it waits for the next signal — it never retries
   the same bar.
