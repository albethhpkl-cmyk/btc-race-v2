# BTC Race Winner Engine — Audit Report v1 + Bot v2

Date: 19 Nov 2026. Account: @laura-jelita (make.fun). Competition:
`btc-race-24h-20261118-1444` (dev window: 1,440 1-min CBBTC bars).
Status labels: VERIFIED = read directly from kit / live API / measured
in the lab; UNVERIFIED = could not be established; ASSUMPTION = stated
as such. **Nothing was submitted. No $90 PnL is promised.**

---

## 1. Audit of bot v1 (VERIFIED)

v1 (submitted 18 Nov, entry `01a1ef5b-d797-7730-966a-f15b8047f28d`):
momentum-breakout, long-only CBBTC — enter when the 5-min return is
≥60 bps OR the 10-min return is ≥80 bps AND the close is above SMA120;
exit on a 65 bps trailing stop or TP +100 bps; 120-bar warmup; insurance
buy of 5% if no trade by bar 1380.

**Reproduction (VERIFIED):** the lab's exact fill model reproduces the
server dev grade to the cent — **net PnL +$6.47, 2 trades (1 round trip:
BUY bar 401 @ 64473.97 → SELL bar 506 @ 64943.07), win rate 1.00, max
drawdown 0.64%**, dev rank #3,006/3,674, prize_rank 2,670.

### 1.1 Why only 2 trades in 24 h

The burst condition is rare in this window. Counts over the 1,440 bars
(VERIFIED from the dataset):

- 5-min return ≥60 bps: **6 bars**; 10-min ≥80 bps: 6 bars;
  60-min ≥100 bps: 6 bars.
- 5 of those 6 burst bars fall inside the 120-bar warmup, so only
  **1 burst bar is tradeable** — and v1 took it (decision bar 400,
  close 64387.21; TP hit at bar 505).
- The SMA120 filter is NOT the main binding constraint: v1 without
  SMA still makes 2 trades (−$0.43). Lowering the burst to 40/50 bps
  gives 6 trades but −$10.26.

The window itself is the cause: 1-min |return| mean 4.00 bps, median
2.53, p90 9.18, p99 25.67, max 63.72 bps; ATR14 mean 4.78 bps. A 60 bps
5-min move is a ~12σ event here. The market is a slow grind, not a
burst market.

### 1.2 TP / SL effectiveness

- TP +100 bps: **effective on the one trade it got** (hit at bar 505,
  +100 bps from entry close, net +$6.47 after costs).
- No stop-loss in v1: the only protection is the 65 bps trailing stop.
  On the single trade it never came close to binding (the trade went
  straight up). With n=1, no statistical claim about the TP/SL pair
  can be made — it is one observation.
- TP50 variant: +$2.02 (worse — exits too early). Trail40: −$4.53
  (worse — chopped out). The v1 exit pair is fine for its one trade;
  it is not the problem. Frequency is the problem, and frequency
  cannot be bought with looser thresholds (see §1.1: 40/50 bps → −$10.26).

### 1.3 Cost per trade (VERIFIED)

- Fee 4 bps + modelled slippage 2 bps per fill, plus constant-product
  price impact vs the bar's open depth.
- Median o_depth $844,015 (mean $840,623) → a $1,000 buy moves its own
  price **≈11.8 bps per side**; the realized v1 round trip cost
  **≈34–35 bps** (fill-to-fill gross +0.99%, net +0.647%) — higher
  than the ~26 bps in RULES.txt, which assumes the frozen $1.38M depth.
- Total fees on v1's dev run: $0.80 (2 fills).

### 1.4 Missed opportunities (VERIFIED, exact fill model, oracle bounds)

- Price-path shape: early dip to ~63,400 by bar 70, long choppy base
  ~63,400–64,000 for ~400 bars, slow grind up to the window max
  65,189.54 at bar 508, then slow grind down to the min 63,076.34 at
  bar 1436. Net drift −2.80%; range 3.35%.
- Best single round trip (oracle): **+$25.13** (buy bar 70 → sell bar 508).
- Optimal unlimited full-size round trips (oracle DP): **+$63.65**
  (28 trades). Total positive 1-min log-return sum 27.36%.
- 159 bars sit inside a trailing 60-bar window containing a ≥100 bps
  low→high move; 2 downtrend stretches contain a trough→peak move
  ≥100 bps (best 160 bps). v1 caught none of the base-to-peak grind —
  it entered at 64,387, after most of the move from the base had
  already happened.
- Mean-reversion edge tests (weak evidence, n=1–7): after a 5-min drop
  ≥80 bps, mean 5-bar forward return +27.18 bps, P(>26 bps cost)=0.50
  (n=6). After a 5-min rise ≥60 bps (v1's trigger), mean 5-bar forward
  +15.82 bps, P(>0)=0.83 (n=6) — the burst signal itself is not bad;
  it is just rare.

### 1.5 Audit verdict on v1

v1 is a correct, well-behaved bot that did exactly what it was built to
do on a window that contains almost no bursts. Its +$6.47 is real
(reproduced to the cent) but fragile: one trade, one window, no
diversification of signal. It is not a frequency problem that looser
thresholds can fix — it is a signal-coverage problem.

---

## 2. Official rules + scoring metric (VERIFIED — kit RULES.txt, competition.yaml, live API)

- **Ranking: net PnL on the race window only** (final cash − $1,000
  start, after every fee, micro-USDC). Tie: fewer trades, then earlier
  receipt; build cost never breaks a tie. The dev window never counts
  toward ranking or prizes — it only decides who races.
- **Dev gate:** the final entry races only if its latest dev grade net
  PnL is **> $0** after every fee/slippage/impact.
- **Guardrails (race window):** **≥1 trade** (the end flatten does not
  count) **and max drawdown ≤25%**, otherwise the entry ranks below
  every entry that meets them and takes no prize.
- **Capital / caps / fills:** start $1,000 USDC paper money; **long
  only, no shorts, no leverage**; cash never below 0; **max 1 open
  position**, up to 100% (10,000 bps) of equity; **max 16 orders/reply**
  (>64 = protocol violation); min buy $1 USDC; an order decided on bar
  k **fills at bar k+1 open**; fee **4 bps per fill** + modelled
  slippage **2 bps** + price impact vs bar open depth (1 + a/D); at
  frozen depth a $1,000 buy moves its own price ~7 bps, full-size
  round trip ≈26 bps per RULES; max_slippage_bps 0–10,000 per order
  (default cap 100 bps vs latest close); everything held at window end
  is sold at the last close; think budget 1,800 s; **two executions
  must produce byte-identical action logs** or the entry is unranked;
  no network, no wall clock, no files outside /bot; Python 3.13
  `python3 -P -s /bot/main.py`, `PYTHONHASHSEED=0`, stdlib + committed
  source only.
- **Prizes ($250 total):** 1st $60, 2nd $40, 3rd $30, 4th $25, 5th $20,
  6th–10th $15 each; top 10 by net PnL even if negative; house bots
  never take a prize; "identical behaviour to an earlier entry" takes
  no prize; ≤10 submissions per entrant per competition.
- **Volume is null.** Bars carry o/h/l/c + depths only; `v: None`
  (RULES.txt: "volume is null (pool state carries none)"). Any
  "volume confirmation" must use the documented price-based proxy
  (bar-range expansion vs ATR + next-bar follow-through), never
  invented volume. No volume was invented in this work.
- **Requirements endpoint:** repo_url + commit_sha + bundle
  (transcripts) + entry_message + entry_signature; LICENSE (OSI) and
  `main.ts`/`main.py` at repo root required.

### Scoring-metric summary (one line)

**Score = net PnL in USDC on the race window, after all costs; the dev
grade is a pass/fail gate (> $0) plus a rehearsal, not the score.
Trade count does not add to the score** — it only breaks ties (fewer
is better) and the ≥1-trade guardrail must be met. **$90 PnL is a
prize-level outcome, not a target the bot can promise:** the dev-top
entry scored $92.40 (see §6).

---

## 3. Bot v2 — architecture

`main.py` (stdlib only, deterministic). Two engines, one open position,
5-bar cooldown after any exit, 5% insurance buy at bar 1380.

- **Engine D — deep-dip swing (primary):** buy 100% when the close is
  ≥150 bps below the trailing 120-bar high. Exits (fixed bps, log
  returns vs entry close): trail 100 bps below peak / TP +200 / SL −300.
- **Engine B — momentum burst (secondary, v1's rule):** buy 100% when
  r5 ≥60 bps or r10 ≥80 bps AND close > SMA120. Exits: trail 65 / TP +100.
- **Volume:** not used (null in the data). **ATR:** computed in the
  lab for regime reporting only; exits are fixed bps because
  ATR-adaptive exits tested worse (−$5.75, §4).

The 4-engine architecture from the directive (Trend EMA 8/21+50,
Momentum RSI/MACD/ROC, Breakout rolling high/low, Volatility ATR) was
built and tested as V1–V5 in the lab. Every one of those engines loses
on this window (§4). Shipping them anyway would mean knowingly
submitting a losing bot, so `main.py` ships only the two validated
engines; the tested-and-rejected variants stay in `lab.py` for the
record. A weighted signal-scoring combiner was also built (V5): the
summed-threshold version scored the dip trade at 55/70 and vetoed it
(−$6.06); the per-engine-threshold version lost −$20.67.

---

## 4. Backtest lab — all variants (frozen dev window, exact fill model)

`python3 lab.py` reproduces every number below. Costs: fee 4 bps +
slip 2 bps per fill + impact vs live depth. Warmup: V1–V4 50–60 bars
(their indicators need less history), V5/DIP/SHIPPED/v1 120 bars.

| Variant | Net PnL | Return | Win | Trades | RT | Max DD | Fees | PF |
|---|---|---|---|---|---|---|---|---|
| buy-and-hold (baseline) | −$31.63 | −3.16% | 0.00 | 1 | 0 | 3.2% | $0.79 | 0.00 |
| hold-cash (baseline) | $0.00 | 0.00% | — | 0 | 0 | 0.0% | $0.00 | — |
| momentum-24bar (baseline) | −$23.87 | −2.39% | 0.00 | 1 | 0 | 3.3% | $0.79 | 0.00 |
| EMA-cross (baseline) | −$148.16 | −14.82% | 0.07 | 80 | 40 | 15.0% | $29.51 | 0.07 |
| RSI-Bollinger (baseline) | −$39.91 | −3.99% | 0.56 | 19 | 9 | 4.4% | $7.89 | 0.22 |
| **v1 submitted** | **+$6.47** | **+0.65%** | **1.00** | **2** | **1** | **0.6%** | **$0.80** | **inf** |
| V1 EMA 8/21 | −$28.42 | −2.84% | 0.25 | 8 | 4 | 3.8% | $3.19 | 0.25 |
| V2 Momentum+RSI | −$15.80 | −1.58% | 0.33 | 6 | 3 | 2.5% | $2.37 | 0.42 |
| V3 Breakout+VolProxy | −$42.42 | −4.24% | 0.00 | 26 | 13 | 4.2% | $10.18 | 0.00 |
| V4 EMA+Momentum | +$1.99 | +0.20% | 0.50 | 4 | 2 | 1.0% | $1.61 | 1.61 |
| V5 Adaptive Multi-Strategy | −$20.67 | −2.07% | 0.25 | 8 | 4 | 3.8% | $3.21 | 0.37 |
| V5-gated | −$20.67 | −2.07% | 0.25 | 8 | 4 | 3.8% | $3.21 | 0.37 |
| DIP-only | +$16.65 | +1.67% | 1.00 | 3 | 1 | 0.8% | $1.62 | inf |
| COMBO ATR-adaptive | +$10.90 | +1.09% | 1.00 | 3 | 1 | 0.8% | $1.61 | inf |
| **SHIPPED v2 (fixed exits)** | **+$16.65** | **+1.67%** | **1.00*** | **3** | **1** | **0.8%** | **$1.62** | **inf** |

\* 1 completed round trip (win). The 3rd trade is a BUY at bar 1437
flattened at window end (−$0.08); the lab does not count the flatten
as a round trip. The protocol replay counts it (win rate 0.50 there).

### Per-hour-block PnL (full window, $; blocks 0–23)

- v1 submitted: `0 0 0 0 0 0 −2.6 +6.9 +2.2 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0` — 2/24 positive.
- V1 EMA 8/21: `0 0 −7.0 −0.5 +0.4 +3.8 +6.2 +4.7 −1.8 −4.0 −4.1 −3.0 +2.0 −0.9 +3.6 −1.4 −0.9 +2.5 −0.6 −6.3 −4.9 −3.1 +0.5 −13.6` — 8/24.
- V2 Momentum+RSI: `0 −11.9 −11.8 −0.5 +0.4 +3.7 +6.1 +4.8 −0.6 −3.9 −2.0 0 0 0 0 0 0 0 0 0 0 0 0 0` — 4/24.
- V3 Breakout: `0 0 0 −2.7 0 −2.1 −8.0 −7.1 −5.4 0 0 0 0 −3.7 −7.8 0 0 −2.1 0 0 0 −3.4 0 0` — 0/24.
- V4 EMA+Momentum: `0 0 0 −6.8 +0.4 +3.8 +6.2 +6.9 −2.4 −4.0 −2.1 0 0 0 0 0 0 0 0 0 0 0 0 0` — 4/24.
- V5 Adaptive: `0 0 −1.3 −0.5 +0.4 +3.8 +6.2 +1.7 +2.7 −4.0 −2.1 0 0 −4.2 +3.6 −1.4 −0.9 +2.6 −0.7 −6.4 0 −7.1 +0.5 −13.7` — 8/24.
- **SHIPPED v2: `0 0 −3.4 −0.5 +0.4 +3.8 +6.2 +6.9 +4.1 0 0 0 0 0 0 0 0 0 0 0 0 0 +1.3` — 6/24 positive.** The profit concentrates in blocks 5–8 (the grind up to the window max); 15 blocks are exactly $0 (flat, no signal).

### Robustness

- **Split-half (chronological train/validation, each half re-installed
  as its own window, $1,000 start):** SHIPPED v2 H1 (bars 0–719)
  **+$17.55** (2 trades) / H2 (720–1439) **−$0.83** (1 trade). v1:
  +$6.47 / $0.00. V5: +$6.98 / −$28.59. V1: −$6.97 / −$27.13.
  The dip edge does not repeat in H2 — one-window evidence, stated
  plainly.
- **2x-fee test (fee 8 bps + slip 4 bps):** SHIPPED v2 **+$14.22**;
  v1 +$5.26; V4 −$0.40; V1 −$33.05; V2 −$19.32; V3 −$57.05;
  V5 −$25.34. The shipped bot stays positive at double cost.
- **Dip parameter plateau (27 cells: drop 120/150/180 × trail
  80/100/120 × TP 150/200/250, SL 300):** +$2.42 to +$17.55, only
  1 cell negative (−$2.10, drop120/trail120/TP250). TP200 best in
  every row. A plateau, not a knife-edge — the one robustness point
  in the dip engine's favour.
- **Size sensitivity:** the shipped engine was validated at 100%
  equity per entry only; no size sweep was run on the shipped exits.
  An earlier size sweep on a different dip variant (tighter exits)
  showed smaller sizes reduce losses but do not create an edge
  (full −$49.75 → 50% −$17.59 → 25% −$6.87 → 10% −$2.28) — that
  variant is not the shipped one and its numbers must not be read as
  a sweep of the shipped bot.
- **Methodology note:** split-half numbers must come from `lab.py`
  `__main__` (namespace-consistent). An earlier ad-hoc script that
  imported `lab` with `from lab import *` then called `set_window()`
  produced an invalid "DIP H2 −$41.76 (28 trades)" — a decision/fill
  mismatch bug, not a real result. The correct H2 is −$0.83 (1 trade).

### v1 vs v2 — head-to-head

| Metric | v1 submitted | v2 SHIPPED | Δ |
|---|---|---|---|
| Net PnL (dev) | +$6.47 | +$16.65 | +$10.18 (2.6×) |
| Return | +0.65% | +1.67% | +1.02 pp |
| Trades / round trips | 2 / 1 | 3 / 1 | +1 trade (end-flatten) |
| Win rate (completed RT) | 1.00 | 1.00 | — |
| Max drawdown | 0.64% | 0.76% | +0.12 pp (still ≪ 25% cap) |
| Total fees | $0.80 | $1.62 | +$0.82 |
| Profit factor | inf | inf | — |
| Positive hour-blocks | 2/24 | 6/24 | +4 |
| 2x-fee PnL | +$5.26 | +$14.22 | +$8.96 |
| Split-half H1 / H2 | +$6.47 / $0.00 | +$17.55 / −$0.83 | better H1, slightly worse H2 |

Trade log (v2, dev window, protocol replay): BUY bar 121 @ 63888.86
→ SELL bar 508 @ 65061.96 (dip swing, +182 bps gross); BUY bar 1437
@ 63157.70 → FLATTEN bar 1439 @ 63152.54 (−$0.08). The burst engine
never fires while flat on this window — its value is entirely as a
second chance on a different (trending) race window.

---

## 5. Final validation

- [x] Lab: SHIPPED v2 +$16.65 (see §4).
- [x] Protocol replay (`python3 validate_local.py --runs 2`): `main.py`
      as a subprocess through the official vendored shim, over the
      frozen dev window: **net PnL +$16.65, return +1.67%, 3 trades,
      max DD 0.76%, total fees $1.62, 2 runs byte-identical action
      logs (56,799 bytes each), exit code 0, no protocol errors,
      ≥1 qualifying trade, DD ≤25%**.
- [ ] **Official `grade-local` NOT run.** It requires Docker for a
      Python bot (the process driver runs node22 only) and this VM
      has no Docker (`docker: command not found`). The local replay
      uses the same fill model that reproduced v1's server dev grade
      (+$6.47) to the cent, but it is not the grader. **Run before any
      submission:** from the kit directory,
      `node cli/makefun.mjs grade-local --kit . --bot <repo> --worktree`
      (default driver Docker), twice, and confirm the two runs match
      and the score agrees with +$16.65.
- [ ] Source commit + build transcript: repo `~/workspace/makefun/btc-race-v2/`,
      commit `a966c48` (see `git log`; re-record the hash if the repo
      changes before submission). Transcripts for submission must be
      generated by the official CLI, not by this local replay.
- [ ] Submission: **NOT submitted.** Awaiting the user's explicit
      approval — this overrides the general auto-submit rule for bot v2.

---

## 6. Top-entry anomaly (RESOLVED in round 2 — see §8.6)

Leaderboard (dev phase, 3,674 entries, VERIFIED live): top-10 all
$92.40; median PnL $12.30; 3,662/3,674 profitable; 99 entries ≥$90;
corr(PnL, trades) = 0.829. The top entry (rey007123,
`01a1f05a-6884-761f-9bd1-f730c3036f36`): **$92.41, 388 trades, win rate
1.000000000, max DD 0.256%, fees $22.68, Sharpe 0.141, exposure 0.376**,
positive in all 24 hour-blocks, $69.27 at 2x fees.

This is **not reconcilable** with the verified fill model under
straightforward position-size arithmetic: fees $22.68 imply total
notional $56,700 (avg ~$146/fill), yet the gross needed is ≈$136
against a ~27% total positive path. Possible explanations (not
proven): rejected orders counted as trades, and/or mixed sizes (many
tiny fills + few large ones). **Do not claim to know the winner's
mechanism.** What it means for v2: the dev-top level (~$92) is far
above anything measured here (+$16.65 best), and the gap is not
explained by "just trade more" — the frequent-trading families tested
here (EMA-cross 80 trades, breakout 26 trades) all lost money.

---

## 7. Honest recommendation

**v2 is fit to be a candidate for the next BTC race — not a favourite,
and not a $90 promise.**

For it:
- Best measured dev result (+$16.65, 2.6× v1), positive at 2x fees
  (+$14.22), DD 0.76% (far inside the 25% cap), deterministic
  (byte-identical logs), protocol-clean, and the dip parameters sit
  on a plateau rather than a knife-edge.
- It fixes v1's real defect (signal coverage: the burst alone fires
  once per window) with a second, independent engine, while keeping
  v1's validated rule as the backup.

Against it / risks:
1. **One-trade dependence.** The entire dev profit is one swing
   (BUY 121 → SELL 508). H2 validation is −$0.83. A race window with
   no ≥150 bps dip and no burst leaves only the 5% insurance trade —
   the bot would qualify (≥1 trade, DD fine) but finish near $0.
2. **$90 is ~5.4× the measured result** and ≈ the dev-top level.
   Nothing tested here gets close; the leaderboard-top mechanism is
   unresolved (§6). Do not enter the next race expecting $90.
3. **One window, one asset, one regime.** All numbers are a single
   24 h sample (dip → grind up → grind down). A trending-up window
   may never trigger the dip; a trending-down window may trigger it
   repeatedly into the SL.
4. **Cost sensitivity to depth.** At live median depth the round trip
   costs ~35 bps; a shallower race window costs more and shrinks the
   already-thin edge.
5. **Official grading not yet done.** `grade-local` (Docker) must
   confirm +$16.65 before submission; a discrepancy there overrides
   everything in this report.

Suggested next steps (in order): (1) run official `grade-local` on
Docker and record the score + transcripts; (2) if it agrees, submit
only with the user's explicit approval; (3) optionally, validate the
V4 EMA+Momentum engine with fixed exits as a possible third engine —
it was +$1.99 standalone and could add coverage on trending windows,
but it has not been validated with fixed exits and must not be added
un-tested.

---

## 8. Round 2 — net PnL maximization (19 Nov 2026)

Goal handed down by the user: make the bot's net PnL beat other users'.
Work: `lab_r2.py` + `lab_r2b.py`. Selection rule (stated before testing):
a candidate replaces SHIPPED v2 only if full-window net PnL > +$16.65
AND split-half H2 >= -$0.83 AND 2x-fee net PnL >= +$14.22.

### 8.1 V4 with fixed exits — validated, NOT shipped

Standalone V4 (EMA+Momentum) with fixed exits (ATR exits in round 1: +$1.99):

| V4 variant | Net PnL | Trades | Win | Split H1 / H2 | 2x-fee |
|---|---|---|---|---|---|
| V4f-A trail65/TP100 | +$1.22 | 4 | 0.50 | +$1.22 / $0.00 (0 tr) | -$1.18 |
| V4f-B trail100/TP200/SL300 | +$5.07 | 2 | 1.00 | +$5.07 / $0.00 (0 tr) | +$3.86 |
| V4f-C trail80/TP150/SL200 | +$12.24 | 2 | 1.00 | +$12.24 / $0.00 (0 tr) | +$11.03 |

V4f-C is the best fixed-exit V4 (+$12.24 vs +$1.99 ATR) — but its edge
is entirely in H1; it fires ZERO times in H2. Combined SHIPPED+V4
(dip + burst + V4f-C, per-engine exits) is **exactly identical to
SHIPPED: +$16.65, same 3 trades, same split-half, same 2x-fee** — for
all three exit sets. Trade-log proof: V4f-C's only round trip is
BUY 222 @ 64076.09 → SELL 505 @ 64912.61; its signals (bars 221–224,
398–399, 404–405, 446, 501) all fall inside the dip position's holding
period (bars 121–508), so the combined bot is already holding and the
V4 entries are blocked. V4 adds coverage only for a DIFFERENT (trending)
race window, not for this one. **DECISION: V4 NOT added to main.py** —
it does not beat SHIPPED on any measured window, and adding an engine
that never fires on the validation window would be cargo-culting.

### 8.2 Pullback continuation (NEW engine) — never fires, NOT shipped

Pure pullback-continuation (uptrend EMA8>EMA21>EMA50 + ≥60 bps pullback
from the 20-bar high while above EMA50 + r5 ≥20 bps recovery + rising
RSI): **zero signals in all 1,440 bars**. Its standalone "trades"
(2 trades, -$0.43 to -$0.64 across the three exit sets) were only the
5% insurance buy and its exit — the engine itself never entered.
Split-half: 0 trades in both halves. **DECISION: not shipped.** A
pullback setup as specified does not exist in this window; the regime
mix explains why (see §8.5).

### 8.3 Hybrid D (regime filter + cost gate) — identical to SHIPPED

All 9 combinations (3 V4 exit sets × 3 pullback exit sets, cost gate on)
give exactly +$16.65 — same reason as §8.1/§8.2: neither new engine
ever enters while flat on this window, so the hybrid IS the shipped
bot here. **Cost-gate bug found and fixed:** the first `rt_cost_bps`
divided dollar notionals by micro-USDC depths and dropped the ×1e4
bps conversion, understating round-trip cost as 12.0 bps. Corrected:
**35.7 bps at median depth** ($844k; bar 500: 33.1 bps; 2x gate
66.3 bps) — matching round 1's "~35 bps". Re-run after the fix:
identical hybrid table, because the gate never bound (no V4/pullback
entry while flat). The gate is real now (TP100 engines block on
shallow-depth bars where 2× RT cost exceeds 100 bps) and stays in
`lab_r2.py` for future windows. **DECISION: no hybrid change to main.py.**

### 8.4 Dip grid expansion + size/cooldown — ONE change adopted

108 cells (drop 120/150/180/210 × trail 80/100/120 × TP 150/200/250 ×
SL 250/300/400), dip-only: **105/108 positive, top +$17.55** — nine
cells tie at +$17.55 (drop 180, TP 200, any trail/SL). The shipped
cell (150/100/200/300) ranks 23rd. Cooldown 0/5/10: no effect on the
best cell. Size sweep on the best cell: 0.50 → +$9.37, 0.75 → +$13.61,
1.00 → +$17.55 — full size wins; smaller sizes only shrink a winning
trade. Combined bot with dip drop=180 (burst + V4f-C still present but
blocked as in §8.1):

| Bot | Net PnL | Trades | DD | Split H1 / H2 | 2x-fee |
|---|---|---|---|---|---|
| SHIPPED v2 (drop150) | +$16.65 | 3 | 0.76% | +$17.55 / -$0.83 | +$14.22 |
| **v2-r2 (drop180)** | **+$17.55** | **2** | **0.76%** | **+$17.55 / $0.00** | **+$16.33** |

All three selection gates pass: +$17.55 > +$16.65; H2 $0.00 >= -$0.83;
2x-fee $16.33 >= $14.22; DD 0.76% < 25%. **DECISION: ADOPTED —
`main.py` DIP_DROP_BPS 150 → 180.** Honest caveat: the +$0.90 comes
entirely from SKIPPING one marginal dip trade (BUY 1437 @ 63157.70,
flattened -$0.08, ~$0.82 in costs) — the winning round trip
(BUY 121 → SELL 508) is unchanged, same bar, same prices. This is a
small, single-trade improvement on a plateau (9 cells tie), not a
breakthrough. Re-validated by protocol replay after the change:
+$17.55, 2 trades, 1 RT, win 1.00, DD 0.76%, fees $0.81, 2 runs
byte-identical action logs (56,689 bytes), exit 0, no protocol errors.

### 8.5 Regime mix — why trend/momentum lose here

Per-bar regime5 over bars 120–1439: bearish 551, sideways 305,
strong_bull 268, weak_bull 129, high_vol 67. The window is 65%
bearish/sideways — trend-following and momentum engines starve while
dip-buying eats. Any future window with a different mix will favour
different engines; that is exactly why V4 stays in `lab_r2.py` as a
tested-but-unshipped option rather than being deleted.

### 8.6 Top-entry anomaly — RESOLVED (as far as the model allows)

New VERIFIED evidence (harness source `sim/metrics.ts`,
`sim/bars/engine.ts`, live API):
- `trades` counts FILLED orders only; rejected orders increment a
  separate `rejected` counter. Top entry: rejected = 0 → the
  "rejected orders counted as trades" hypothesis is REFUTED.
- End flatten has kind `flatten`, not `order` → does NOT count as a trade.
- `exposure` = mean over batches of (equity − cash)/equity; top = 0.376.
- Leaderboard net PnL is rounded to 3 significant figures: the "21
  entries at exactly $92.40" are 21 entries in [$92.35k, $92.45k).
  Top-10 trades 385–390, DD ≈0.00256, Sharpe ≈0.141 — one strategy
  family with small variations, 99 distinct handles ≥$90.
- 99 entries ≥$90 (trades 212–1063, median 369); overall median
  trades is 4; only 169/3,674 entries trade ≥100 times.
- **Partial-size DP oracle (new, `lab_r2b.py`): perfect foresight with
  ANY position size and exact fill costs gives +$108.28 (0.001 BTC
  steps, 247 switches) / +$111.33 (0.0005 steps, 271 switches).** The
  independent bang-bang DP reproduces round 1's $63.65 exactly.
  Conclusion: $92.41 is BELOW the perfect-foresight bound — achievable
  in principle, but only with near-perfect foresight and ~200 small-size
  round trips harvesting 12–36 bps moves that full-size trading cannot
  afford (RT cost ~12 bps small vs ~36 bps full-size). That is
  dev-window overfitting (the window is published) or an exceptional
  HF strategy; either way it does NOT transfer to the unseen race
  window, and no causal strategy tested here comes close.

### 8.7 v1 vs v2 vs v2-r2

| Metric | v1 submitted | v2 SHIPPED | **v2-r2 (current)** |
|---|---|---|---|
| Net PnL (dev) | +$6.47 | +$16.65 | **+$17.55** |
| Return | +0.65% | +1.67% | **+1.75%** |
| Trades / round trips | 2 / 1 | 3 / 1 | **2 / 1** |
| Win rate (completed RT) | 1.00 | 1.00 | **1.00** |
| Max drawdown | 0.64% | 0.76% | **0.76%** |
| Total fees | $0.80 | $1.62 | **$0.81** |
| 2x-fee PnL | +$5.26 | +$14.22 | **+$16.33** |
| Split-half H1 / H2 | +$6.47 / $0.00 | +$17.55 / -$0.83 | **+$17.55 / $0.00** |
| Gap to dev-top $92.41 | $85.94 | $75.76 | **$74.86 (5.3×)** |

### 8.8 Honest recommendation (round 2)

**v2-r2 is the candidate for the next BTC race — the best measured
bot we have, and still nowhere near the dev-top level.** The remaining
gap ($74.86) is a FORESIGHT gap, not a parameter gap: the DP oracle
says even perfect foresight caps at ~$108–111, and every causal
engine family tested (trend, momentum, breakout, adaptive, pullback,
V4, hybrid) is at or below +$17.55 on this window. Further tuning on
this single window will only overfit it harder. Sensible next steps,
in order: (1) run official `grade-local` on Docker and record the
score + transcripts; (2) if it agrees, submit ONLY with the user's
explicit approval; (3) for real progress, validate the shipped bot on
OTHER competitions' published dev windows (generalization test) rather
than squeezing this one — a bot that is +$17 on one window and ~$0 on
others is a one-window bot, and the race window is a different window.

## 9. Sources (all read directly)

- `https://make.fun/skill.md` v1.5.220 (read live 19 Nov 2026).
- Kit `btc-race-24h-20261118-1444-kit/`: `RULES.txt`,
  `competition.yaml`, `dataset/bars/CBBTC.ndjson.gz` (1,440 bars),
  `dataset/manifest.json`, baselines (`rsi-bollinger`, `adx-momentum`,
  `momentum`), `sdk/makefun_bars.py`, `protocol.schema.json`.
- Live API: `/api/competitions/btc-race-24h-20261118-1444` (+
  `/requirements`, `/leaderboard`), `/api/submissions/01a1ef5b-…`
  (v1) and `/api/submissions/01a1f05a-…` (top entry).
- `~/workspace/makefun/btc-race-20261118-1444/backtest.py` (v1
  backtester — not modified).
