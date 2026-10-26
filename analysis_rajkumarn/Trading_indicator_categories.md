# Indicator Categories for Behaviour-Based Pattern Discovery

## Purpose

Classify indicators by what their values represent and how they relate
to price. Categories can overlap: MACD, for example, is both
multi-component and momentum-related. Use data structure to decide which
calculations are valid, then indicator meaning to select useful
behaviours.

## 1. Single-value oscillators

**Examples:** RSI, CCI, MFI.\
**Represents:** bounded or unbounded momentum, pressure, or relative
strength.\
**Analyze:** level/change, threshold distance, rise/fall, acceleration,
time above/below thresholds, local peaks/troughs, extreme-zone
entry/exit, divergence from price.\
**Caution:** percentage change can mislead near zero or for bounded
oscillators; use point changes and meaningful threshold distances where
appropriate.

## 2. Multi-component indicators

**Examples:** MACD line, signal line, histogram; stochastic %K and %D.\
**Represents:** related components describing momentum, smoothing,
separation, or confirmation.\
**Analyze:** each component, differences between components,
convergence/divergence, crossovers, failed crossovers, component
ordering, same/opposite direction, leading/lagging, histogram
expansion/contraction and sign changes.\
**Caution:** components may be highly related; do not count redundant
representations as independent confirmations.

## 3. Single price-reference indicators

**Examples:** SMA, EMA, VWAP.\
**Represents:** a reference price level for comparison with market
price.\
**Analyze:** price-reference distance in points and normalized units,
price above/below, crossings, touches/rejections/bounces, reference
slope, distance shrinking/expanding, agreement between reference lines.\
**Caution:** raw point distances depend on price/volatility regime;
consider ATR or another appropriate scale.

## 4. Multi-value price envelopes/bands

**Examples:** Bollinger Bands, Keltner Channels, Donchian Channels.\
**Represents:** upper/lower boundaries, sometimes with a middle
reference.\
**Analyze:** price position inside/outside, distance to boundaries,
width and normalized width, expansion/contraction, band slopes,
touches/rejections, breakouts and returns, breakout after compression.\
**Caution:** handle zero/nearly-zero width; a band touch is not
inherently bullish or bearish.

## 5. Volatility and range indicators

**Examples:** ATR, historical volatility, true range.\
**Represents:** movement magnitude or variability, not necessarily
direction.\
**Analyze:** rising/falling volatility, expansion/contraction, spikes,
regime changes, candle range relative to volatility, normalization after
a spike, volatility changes alongside price/momentum.\
**Caution:** rising ATR alone does not imply rising prices.

## 6. Directional movement and trend-strength indicators

**Examples:** ADX, +DI, −DI.\
**Represents:** trend strength and/or the balance of upward and downward
directional movement.\
**Analyze:** trend strength rising/falling, +DI versus −DI, their
difference, crossovers, convergence/divergence, directional dominance,
strong trend with weakening momentum.\
**Caution:** ADX measures trend strength, not direction by itself.

## 7. Volume and flow indicators

**Examples:** volume, OBV, MFI, cumulative volume delta where
available.\
**Represents:** trading activity, cumulative volume direction, or an
estimate of buying/selling pressure.\
**Analyze:** relative volume, spikes, rising/falling flow, price-volume
confirmation/divergence, OBV slope, volume rising while price movement
weakens.\
**Caution:** raw volume often has time-of-day patterns; normalize
against comparable periods when appropriate. Data availability and
interpretation vary by instrument/source.

## 8. Discrete or state-based indicators

**Examples:** Supertrend direction, buy/sell flags, categorical candle
patterns, regime labels.\
**Represents:** a state, class, event, or direction label rather than
continuous magnitude.\
**Analyze:** state and transitions, duration, persistence, flip
frequency, repeated flips, stabilization, state sequences,
agreement/disagreement across indicators, time since transition.\
**Caution:** do not calculate ordinary percentage changes or slopes on
categorical labels; encode states and transitions explicitly.

## Cross-cutting implementation metadata

For each indicator, maintain: family, component names, value type,
whether zero is meaningful, whether thresholds are meaningful, whether
price comparison applies, whether percentage change is appropriate,
recommended normalization, and applicable behaviours.

These are practical engineering groups, not mutually exclusive
mathematical classes. Generate only valid, interpretable features and
use validation to determine usefulness.
