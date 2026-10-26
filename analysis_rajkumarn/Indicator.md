# Indicators

## 1. Summary

| # | Indicator | What it reads | Settings (versions in section 2) | Needs volume | Outputs | Checked by |
|---|---|---|---|---|---|---|
| 1 | Range Filter | trend, with noise filtered out | v1: source (O+H+L+C)/4, sampling period 50, multiplier 3 | no | filter line, high band, low band, direction, state, buy, sell | independent rebuild from the Pine script: identical on 15,300 candles |
| 2 | HalfTrend | trend flips from swing structure | v1: amplitude 2, channel deviation 2, ATR length 100 | no | line, trend, buy, sell | independent rebuild from the Pine script: identical on 15,300 candles |
| 3 | CLV (close location value) | who won the candle | none | no | value from -1 to +1 | worked example |
| 4 | Wick ratio | rejection of a price extreme | none | no | lower wick ratio, upper wick ratio | worked example |
| 5 | Candle sweep | a stop-hunt past the previous candle's extreme | none | no | bull, bear, depth %, reclaim % | worked example |
| 6 | Zero-lag sweep | a stop-hunt by the last minute of the current candle | none (needs a timeframe of 2 minutes or more) | no | bull, bear | worked examples |
| 7 | Colour, flip, engulf, range break | change of control between two candles | none | no | colour, flip bull / bear, engulf bull / bear, break up / down | worked example |

**A candle is named by its last minute.** The 5-minute candle 11:23..11:27 is the 11:27 candle (TradingView names the same candle by its first minute, 11:23).

Every indicator runs on every timeframe (1, 2, 3, 5, 8, 13, 21, 34 minutes) on **rolling candles**: the row at 11:27 holds the N-minute candle that ends at 11:27, so the 5-minute candle there is 11:23..11:27. Open = open of its first minute, high = highest high, low = lowest low, close = close of its last minute, volume = the sum of its minutes' volumes. "The previous candle" is the one that does not overlap: N minutes back (for the 5-minute candle at 11:27, the candle 11:18..11:22); when N minutes back is before the session start, it is the previous session's last candle (for the 5-minute candles at 09:15 .. 09:19, the candle 15:25..15:29 of the previous session). No candle spans two days: in the first minutes of a session the N-minute candle holds only the session's minutes so far (at 09:17 the 5-minute candle is 09:15..09:17), so every timeframe has a value from the session's first minute. Only completed candles are used.

Indicators 1 and 2 come from TradingView; their Pine scripts are saved below as received. Indicators 3 to 7 are defined by formula only.

---

## 2. Definitions

### 2.1 Range Filter

**Source:** TradingView "Range Filter Buy and Sell 5min" by DonovanWall, adapted by guikroth, Pine v5.

**Parameters**

| Parameter | Script default | v1 (user, 2026-10-03) |
|---|---|---|
| Source | close | (O+H+L+C)/4 (`ohlc4`) |
| Sampling Period | 100 | 50 |
| Range Multiplier | 3.0 | 3.0 |

A new set of values becomes v2, v3, ... in a new column; a run says which version it used. The formula and sample below use v1.

**Warm-up** (how many candles of the timeframe it runs on, one after another, it needs before its values can be used)

| | v1 |
|---|---|
| Minimum, to the first line value | 149 candles (= 3 x sampling period - 1: 50 moves for the first average, then 99 of those for the second) |
| Recommended, until the starting point has faded | about 450 candles (the minimum plus 3 x 99, after which the slow average keeps well under 1% of its starting value) |

**Formula**
1. `src = (O + H + L + C) / 4`.
2. `move = |src - previous src|`.
3. `avrng = EMA(move, 50)`, then `range = EMA(avrng, 2 x 50 - 1 = 99) x 3`. The range is about three times the typical candle-to-candle move.
4. **Filter line** (a ratchet that only steps):
   - if `src > previous line`: line = `src - range`, but never lower than the previous line;
   - otherwise: line = `src + range`, but never higher than the previous line.
5. `high band = line + range`, `low band = line - range`.
6. **Direction**: +1 while the line's last move was up, -1 while it was down, 0 before its first move.
7. **Long condition**: src above the line, direction +1, and src changed from the previous candle. **Short condition**: the mirror.
8. **State** remembers the last condition (+1 long, -1 short). **Buy** = the first long condition after a short state; **Sell** = the first short condition after a long state. Buys and sells always alternate.

**Pine details the framework reproduces:** `nz()` turns an empty previous line into 0, so the first line value is `src - range`; a comparison with an empty value is false; an EMA is empty until `length` values exist and then starts from their simple average.

**Pine script** (as received from TradingView; also in `pine/range_filter.pine`)
```pine
//@version=5
indicator(title="Range Filter Buy and Sell 5min", shorttitle="Range Filter", overlay=true)

// Original Script > @DonovanWall
// Adapted Version > @guikroth
//
// Updated PineScript to version 5
// Republished by > @tvenn

//////////////////////////////////////////////////////////////////////////
// Settings for 5min chart, BTCUSDC. For Other coin, change the parameters
//////////////////////////////////////////////////////////////////////////

// Color variables
upColor   = color.white
midColor  = #90bff9
downColor = color.blue

// Source
src = input(defval=close, title="Source")

// Sampling Period
// Settings for 5min chart, BTCUSDC. For Other coin, change the paremeters
per = input.int(defval=100, minval=1, title="Sampling Period")

// Range Multiplier
mult = input.float(defval=3.0, minval=0.1, title="Range Multiplier")

// Smooth Average Range
smoothrng(x, t, m) =>
    wper = t * 2 - 1
    avrng = ta.ema(math.abs(x - x[1]), t)
    smoothrng = ta.ema(avrng, wper) * m
    smoothrng
smrng = smoothrng(src, per, mult)

// Range Filter
rngfilt(x, r) =>
    rngfilt = x
    rngfilt := x > nz(rngfilt[1]) ? x - r < nz(rngfilt[1]) ? nz(rngfilt[1]) : x - r :
       x + r > nz(rngfilt[1]) ? nz(rngfilt[1]) : x + r
    rngfilt
filt = rngfilt(src, smrng)

// Filter Direction
upward = 0.0
upward := filt > filt[1] ? nz(upward[1]) + 1 : filt < filt[1] ? 0 : nz(upward[1])
downward = 0.0
downward := filt < filt[1] ? nz(downward[1]) + 1 : filt > filt[1] ? 0 : nz(downward[1])

// Target Bands
hband = filt + smrng
lband = filt - smrng

// Colors
filtcolor = upward > 0 ? upColor : downward > 0 ? downColor : midColor
barcolor = src > filt and src > src[1] and upward > 0 ? upColor :
   src > filt and src < src[1] and upward > 0 ? upColor :
   src < filt and src < src[1] and downward > 0 ? downColor :
   src < filt and src > src[1] and downward > 0 ? downColor : midColor

filtplot = plot(filt, color=filtcolor, linewidth=2, title="Range Filter")

// Target
hbandplot = plot(hband, color=color.new(upColor, 70), title="High Target")
lbandplot = plot(lband, color=color.new(downColor, 70), title="Low Target")

// Fills
fill(hbandplot, filtplot, color=color.new(upColor, 90), title="High Target Range")
fill(lbandplot, filtplot, color=color.new(downColor, 90), title="Low Target Range")

// Bar Color
barcolor(barcolor)

// Break Outs
longCond = bool(na)
shortCond = bool(na)
longCond := src > filt and src > src[1] and upward > 0 or
   src > filt and src < src[1] and upward > 0
shortCond := src < filt and src < src[1] and downward > 0 or
   src < filt and src > src[1] and downward > 0

CondIni = 0
CondIni := longCond ? 1 : shortCond ? -1 : CondIni[1]
longCondition = longCond and CondIni[1] == -1
shortCondition = shortCond and CondIni[1] == 1

//Alerts
plotshape(longCondition, title="Buy Signal", text="Buy", textcolor=color.white, style=shape.labelup, size=size.small, location=location.belowbar, color=color.new(#aaaaaa, 20))
plotshape(shortCondition, title="Sell Signal", text="Sell", textcolor=color.white, style=shape.labeldown, size=size.small, location=location.abovebar, color=color.new(downColor, 20))


alertcondition(longCondition, title="Buy alert on Range Filter", message="Buy alert on Range Filter")
alertcondition(shortCondition, title="Sell alert on Range Filter", message="Sell alert on Range Filter")
alertcondition(longCondition or shortCondition, title="Buy and Sell alert on Range Filter", message="Buy and Sell alert on Range Filter")


// For use as a Strategy
// ___________________________________________________________________________________________________________

// 1. Replace the word "indicator" on line 2 with the word "strategy"
// 2. Uncomment the code below by highlighting it and pressing Ctl + '/'

// Settings for 5min BTCUSDT. For other timeframes and assets, adjust the parameters within the settings menu.
// ___________________________________________________________________________________________________________

// grp_STRAT   = "Strategy settings"
// timeInput   = input.time(timestamp("1 Nov 2022 00:00 +0000"), title="Start date", group=grp_STRAT)
// tpInPips    = input.int(400, title="TP (in pips)", group=grp_STRAT)
// slInPips    = input.int(100, title="SL (in pips)", group=grp_STRAT)

// timePeriod  = time >= timeInput
// notInTrade  = strategy.position_size <= 0

// if(longCondition and timePeriod and notInTrade)
//     strategy.entry("Long", strategy.long)
//     strategy.exit("Exit long", "Long", loss=slInPips, profit=tpInPips)
// if(shortCondition and timePeriod and notInTrade)
//     strategy.entry("Short", strategy.short)
//     strategy.exit("Exit short", "Short", loss=slInPips, profit=tpInPips)
```
To match v1 on TradingView: Source = (O+H+L+C)/4 (`ohlc4`), Sampling Period = 50, Range Multiplier = 3.

**How to read it**
- The line stays flat through small moves and moves only when price travels more than one range away; it then trails price one range behind.
- **Buy** = price has pushed far enough above the line to drag it up for the first time since the last Sell.
- It is late by design: it waits for a move larger than about three average candles, removing noise but giving up the start of each move.
- Outputs used by the framework: `rf_buy`, `rf_sell` (events), `rf_dir` (direction), `rf_state`, `rf_filt`, `rf_hband`, `rf_lband`.

**Sample input and output** (NIFTY, 2026-01-05, clock-aligned 5-minute candles 09:15..09:19, 09:20..09:24, ..., each named by its last minute: the candle 09:30..09:34 is the 09:34 candle; TradingView shows the same candle at 09:30, its first minute)

| candle | O | H | L | C | src | line | range | direction | state | signal |
|---|---|---|---|---|---|---|---|---|---|---|
| 09:29 | 26300.20 | 26323.25 | 26287.65 | 26301.60 | 26303.18 | 26318.29 | 16.35 | +1 | +1 | |
| **09:34** | 26301.20 | 26301.65 | 26269.50 | 26272.35 | 26286.18 | **26302.58** | 16.41 | **-1** | -1 | **Sell** |
| 09:39 | 26272.60 | 26282.65 | 26263.60 | 26278.15 | 26274.25 | 26290.73 | 16.48 | -1 | -1 | |
| 09:54 | 26299.10 | 26311.65 | 26285.50 | 26305.00 | 26300.31 | 26290.73 | 16.71 | -1 | -1 | |
| **09:59** | 26305.10 | 26326.50 | 26303.75 | 26316.90 | 26313.06 | **26296.26** | 16.80 | **+1** | +1 | **Buy** |

- 09:34: src 26286.18 is below the previous line 26318.29, so the line moves to src + range = 26286.18 + 16.41 = 26302.59 (lower than before, allowed). The line moved down and the state was long, so this is a **Sell**.
- 09:54: src 26300.31 is above the line, but src - range = 26283.60 is below the line 26290.73, so the line stays flat.
- 09:59: src - range = 26313.06 - 16.80 = 26296.26 is above the line 26290.73, so the line steps up to 26296.26. The line moved up and the state was short, so this is a **Buy**.

---

### 2.2 HalfTrend

**Source:** TradingView "HalfTrend" by Alex Orekhov (everget), Pine v6, GPL-3.0.

**Parameters**

| Parameter | Script default | v1 (user, 2026-10-04) |
|---|---|---|
| Amplitude | 2 | 2 |
| Channel Deviation | 2 | 2 |
| ATR length | 100 (written into the script, not an input) | 100 |

v1 is the script's defaults (the user chose them until the setup is in use; ATR 30 was mentioned and set aside). A new set of values becomes v2, v3, ... in a new column; a run says which version it used. The formula and sample below use v1.

**Warm-up** (how many candles of the timeframe it runs on, one after another, it needs before its values can be used)

| | v1 |
|---|---|
| Minimum, to the first signal | 100 candles (the ATR length; before that no Buy or Sell can fire, although the line and trend are already computed) |
| Recommended | 100 candles: the trend logic looks back only `amplitude` (2) candles, and its starting state is gone at its first flip, which comes within a few candles; the ATR's own starting point affects only the drawn channel, not the signals |

**Formula** (amplitude = 2, so "recent" means the last 2 candles)
1. `highPrice` = highest high of the recent candles, `lowPrice` = lowest low; `highma` = average of the recent highs, `lowma` = average of the recent lows.
2. **While in an uptrend** (trend = up), track `maxLowPrice` = the highest of the recent lows since the uptrend began (it only rises). Flip to **down** when `highma < maxLowPrice` **and** close < the previous candle's low.
3. **While in a downtrend**, track `minHighPrice` = the lowest of the recent highs since the downtrend began (it only falls). Flip to **up** when `lowma > minHighPrice` **and** close > the previous candle's high.
4. **Line:** in an uptrend `up = max(maxLowPrice, previous up)` (only steps up); in a downtrend `down = min(minHighPrice, previous down)` (only steps down); on a flip, the new line starts where the old one ended.
5. **Buy** = the candle where the trend flips from down to up; **Sell** = up to down. They always alternate.
6. ATR(100) / 2 and the channel deviation only place the arrows and the channel around the line, and hold back any signal until 100 candles exist. **Only amplitude changes the signals.**

**Pine script** (as received from TradingView; also in `pine/halftrend.pine`)
```pine
//@version=6
// Copyright (c) 2021-present, Alex Orekhov (everget)
// HalfTrend script may be freely distributed under the terms of the GPL-3.0 license.
indicator('HalfTrend', overlay = true)

const string calcGroup = 'Calculation'
amplitude = input.int(2, title = 'Amplitude', group = calcGroup)
channelDeviation = input.int(2, title = 'Channel Deviation', group = calcGroup)

const string visualGroup = 'Visuals'
showArrows = input.bool(true, title = 'Show Arrows', group = visualGroup)
showChannels = input.bool(true, title = 'Show Channels', group = visualGroup)
showLabels = input.bool(true, title = 'Show Buy/Sell Labels', group = visualGroup)

//---

var int trend = 0
var int nextTrend = 0
var float maxLowPrice = nz(low[1], low)
var float minHighPrice = nz(high[1], high)

var float up = 0.0
var float down = 0.0
float atrHigh = 0.0
float atrLow = 0.0
float arrowUp = na
float arrowDown = na

atr2 = ta.atr(100) / 2
dev = channelDeviation * atr2

highPrice = high[math.abs(ta.highestbars(amplitude))]
lowPrice = low[math.abs(ta.lowestbars(amplitude))]
highma = ta.sma(high, amplitude)
lowma = ta.sma(low, amplitude)

if nextTrend == 1
    maxLowPrice := math.max(lowPrice, maxLowPrice)

    if highma < maxLowPrice and close < nz(low[1], low)
        trend := 1
        nextTrend := 0
        minHighPrice := highPrice
        minHighPrice
else
    minHighPrice := math.min(highPrice, minHighPrice)

    if lowma > minHighPrice and close > nz(high[1], high)
        trend := 0
        nextTrend := 1
        maxLowPrice := lowPrice
        maxLowPrice

if trend == 0
    if not na(trend[1]) and trend[1] != 0
        up := na(down[1]) ? down : down[1]
        arrowUp := up - atr2
        arrowUp
    else
        up := na(up[1]) ? maxLowPrice : math.max(maxLowPrice, up[1])
        up
    atrHigh := up + dev
    atrLow := up - dev
    atrLow
else
    if not na(trend[1]) and trend[1] != 1
        down := na(up[1]) ? up : up[1]
        arrowDown := down + atr2
        arrowDown
    else
        down := na(down[1]) ? minHighPrice : math.min(minHighPrice, down[1])
        down
    atrHigh := down + dev
    atrLow := down - dev
    atrLow

ht = trend == 0 ? up : down

const color buyColor = color.blue
const color sellColor = color.red
const color textColor = color.white
const color buyFillColor = color.new(buyColor, 85)
const color sellFillColor = color.new(sellColor, 85)

htColor = trend == 0 ? buyColor : sellColor
htPlot = plot(ht, title = 'HalfTrend', linewidth = 2, color = htColor)

atrHighPlot = plot(showChannels ? atrHigh : na, title = 'ATR High', style = plot.style_circles, color = sellColor)
atrLowPlot = plot(showChannels ? atrLow : na, title = 'ATR Low', style = plot.style_circles, color = buyColor)

fill(htPlot, atrHighPlot, title = 'ATR High Ribbon', color = sellFillColor)
fill(htPlot, atrLowPlot, title = 'ATR Low Ribbon', color = buyFillColor)

buySignal = not na(arrowUp) and trend == 0 and trend[1] == 1
sellSignal = not na(arrowDown) and trend == 1 and trend[1] == 0

plotshape(showArrows and buySignal ? atrLow : na, title = 'Arrow Up', style = shape.triangleup, location = location.absolute, size = size.tiny, color = buyColor)
plotshape(showArrows and sellSignal ? atrHigh : na, title = 'Arrow Down', style = shape.triangledown, location = location.absolute, size = size.tiny, color = sellColor)

plotshape(showLabels and buySignal ? atrLow : na, title = 'Buy Label', text = 'Buy', location = location.absolute, style = shape.labelup, size = size.tiny, color = buyColor, textcolor = textColor)
plotshape(showLabels and sellSignal ? atrHigh : na, title = 'Sell Label', text = 'Sell', location = location.absolute, style = shape.labeldown, size = size.tiny, color = sellColor, textcolor = textColor)

alertcondition(buySignal, title = 'HalfTrend Buy', message = 'HalfTrend Buy, {{exchange}}:{{ticker}}')
alertcondition(sellSignal, title = 'HalfTrend Sell', message = 'HalfTrend Sell, {{exchange}}:{{ticker}}')
```
In the script `trend = 0` means up and `trend = 1` means down; the framework writes them as `ht_trend` = +1 (up) and -1 (down).

**How to read it**
- It flips when price has made a lower structure (the recent highs are under the uptrend's best low) **and** a candle closes past the previous candle's range.
- With amplitude 2 it reacts within a few candles: faster and noisier than the Range Filter.
- Outputs used by the framework: `ht_buy`, `ht_sell` (events), `ht_trend` (direction), `ht_line`.

**Sample input and output** (NIFTY, 2026-01-05, the same clock-aligned 5-minute candles as 2.1, each named by its last minute)

| candle | O | H | L | C | line | trend | signal |
|---|---|---|---|---|---|---|---|
| 09:29 | 26300.20 | 26323.25 | 26287.65 | 26301.60 | 26321.75 | up | |
| **09:34** | 26301.20 | 26301.65 | 26269.50 | 26272.35 | 26321.75 | **down** | **Sell** |
| 09:39 | 26272.60 | 26282.65 | 26263.60 | 26278.15 | 26301.65 | down | |
| 10:09 | 26292.00 | 26336.40 | 26285.10 | 26335.35 | 26296.95 | down | |
| **10:14** | 26334.80 | 26342.30 | 26331.75 | 26339.15 | 26296.95 | **up** | **Buy** |

- 09:34: the average of the last 2 highs, (26323.25 + 26301.65) / 2 = 26312.45, is below the uptrend's best low 26321.75, and the close 26272.35 is below the previous low 26287.65: **Sell**. The new down line starts from the old up line, 26321.75.
- 10:14: the average of the last 2 lows, (26285.10 + 26331.75) / 2 = 26308.43, is above the downtrend's lowest high 26296.95, and the close 26339.15 is above the previous high 26336.40: **Buy**. The new up line starts from the old down line, 26296.95.

---

### 2.3 CLV (close location value)

**Source:** the user's reversal notes (`Trading-Reversal_MarketConsolidation_Indicators.txt`, check 1).

**Formula:** `CLV = ((C - L) - (H - C)) / (H - L)`; 0 when H = L.

**Warm-up:** the current candle only; no memory.

**How to read it**

| CLV | Meaning |
|---|---|
| +0.5 .. +1 | closed near the high: buyers won the candle |
| 0 .. +0.5 | mildly bullish |
| -0.5 .. 0 | mildly bearish |
| -1 .. -0.5 | closed near the low: sellers won the candle |

On its own it only says who won this candle. It hints at a reversal when it is the opposite of what came before, for example CLV above +0.5 now after a previous candle below -0.5.

**Sample input and output** (5-minute candle)

| | O | H | L | C | CLV |
|---|---|---|---|---|---|
| current | 25020 | 25041 | 25004 | 25039 | ((25039 - 25004) - (25041 - 25039)) / 37 = 33 / 37 = **+0.89** |
| previous | 25022 | 25030 | 25015 | 25020 | ((5) - (10)) / 15 = **-0.33** |

Control moved from mildly bearish to clearly bullish.

---

### 2.4 Wick ratio

**Source:** the user's reversal notes, check 2.

**Formula**
- Lower wick ratio = `(min(O, C) - L) / (H - L)`: rejection of lower prices, read for upward turns.
- Upper wick ratio = `(H - max(O, C)) / (H - L)`: rejection of higher prices, read for downward turns.
- Both are 0 when H = L.

**Warm-up:** the current candle only; no memory.

**How to read it**

| Ratio | Meaning |
|---|---|
| above 0.5 | strong rejection: more than half the candle is wick |
| 0.3 .. 0.5 | moderate rejection |
| below 0.3 | weak or none |

In a very strong reversal the close runs far from the open, the wick becomes body and the ratio falls, so read it together with CLV.

**Sample input and output** (the current candle of 2.3: O 25020, H 25041, L 25004, C 25039)
- Lower: (min(25020, 25039) - 25004) / 37 = 16 / 37 = **0.43** (moderate rejection of the lows).
- Upper: (25041 - max(25020, 25039)) / 37 = 2 / 37 = **0.05**.

---

### 2.5 Candle sweep

**Source:** the user's reversal notes, check 3.

**Formula** (current candle against the previous candle)
- **Bull sweep:** `L < L_prev and C > L_prev`: took out the previous low and closed back above it.
- **Bear sweep:** `H > H_prev and C < H_prev`.
- **Depth** = how far past the old extreme (`L_prev - L`, or `H - H_prev`); **reclaim** = how far it closed back (`C - L_prev`, or `H_prev - C`). The framework stores both as % of the close.
- **Strong sweep:** reclaim > depth.

**Warm-up:** the current and the previous candle; no memory.

**How to read it**
- Stops below the old low were triggered and sellers could not hold the lower price: a hint of an upward turn.
- A close that stays below the old low is a breakdown (the move continues), not a sweep.
- Stronger when it recovers more than it overshot (reclaim > depth).

**Sample input and output** (current L 25004, C 25039; previous L 25015)
- L 25004 < 25015 and C 25039 > 25015: **bull sweep**.
- Depth = 25015 - 25004 = 11 points (0.044% of the close); reclaim = 25039 - 25015 = 24 points (0.096%). Reclaim > depth: **strong**.

---

### 2.6 Zero-lag sweep

**Source:** the user's reversal notes, check 4.

**Formula** (for an N-minute candle ending at minute T, N of 2 or more)
- `Range_High` = highest high of minutes T-N+1 .. T-1; `Range_Low` = lowest low of the same minutes (the candle without its last minute).
- **Bull:** `L_T < Range_Low and C_T > Range_Low`: the last minute took out the block's low and closed back above it.
- **Bear:** `H_T > Range_High and C_T < Range_High`.
- Not defined for 1 minute. On 2 minutes it is the 1-minute candle sweep.

**Warm-up:** the N one-minute candles of the current block, inside the same day; no memory.

**How to read it**
- The same idea as the candle sweep at a finer level. It can fire one minute after the sweep, so it is the earliest of the reversal checks.
- Stronger when the last minute also closes in the upper half of its own range (1-minute CLV above 0 for bull).

**Sample input and output** (5-minute blocks)

| decision minute | block minutes | Range_High / Range_Low | last minute H / L / C | result |
|---|---|---|---|---|
| 11:24 | 11:20..11:23 | 25027 / 25009 | - / 25004 / 25016 | L 25004 < 25009 and C 25016 > 25009: **bull** |
| 11:27 | 11:23..11:26 | 25034 / 25004 | 25041 / 25030 / 25039 | H 25041 > 25034 but C 25039 also > 25034: a breakout, **no sweep**; L 25030 not below 25004: **no bull** |

---

### 2.7 Colour, flip, engulf, range break

**Source:** the user's reversal notes, check 5.

**Formula** (current candle against the previous candle)
- **Colour:** +1 green (C > O), -1 red (C < O), 0 flat. On rolling candles the open is the price N minutes ago, so green means "higher than N minutes ago".
- **Flip:** bull = previous red and current green; bear = previous green and current red.
- **Classic engulf:** bull = bull flip and `O <= C_prev and C >= O_prev`; bear = bear flip and `O >= C_prev and C <= O_prev`. On continuous intraday data the open is almost always the previous close, so this mostly means "this candle's rise is at least the previous candle's fall".
- **Range break:** up = `C > H_prev`; down = `C < L_prev`. Kept separate from the flip so the two can be combined.

**Warm-up:** the current and the previous candle; no memory.

**How to read it**
- A flip alone is weak: a tiny green candle also counts.
- Flip + classic engulf: momentum reversed.
- Flip + range break: the turn is established on that timeframe.
- The notes prefer flips on the 5- and 10-minute candles; the 2-minute one flips often.

**Sample input and output** (5-minute candles: previous O 25022, H 25030, L 25015, C 25020; current O 25020, H 25041, L 25004, C 25039)

| Check | Calculation | Result |
|---|---|---|
| Colour | previous 25020 < 25022: red; current 25039 > 25020: green | **bull flip** |
| Classic engulf | O 25020 <= C_prev 25020 and C 25039 >= O_prev 25022 | **yes** |
| Range break | C 25039 > H_prev 25030 | **break up** |
| Same check on the 10-minute candle (H_prev 25063) | C 25039 < 25063 | no break: the larger candle has not turned yet |
