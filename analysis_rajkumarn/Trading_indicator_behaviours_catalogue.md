# Indicator Behaviour Catalogue for Pattern Discovery

This catalogue contains the 180 candidate behaviours from the discussion, grouped by theme. These are candidate descriptions, not 180 independent features or proven trading signals. Some overlap, and some apply only to specific indicator families.

## 1. Value and magnitude behaviours
1. Rising
2. Falling
3. Flat / stable
4. Shrinking toward zero
5. Expanding away from zero
6. Approaching a threshold
7. Moving away from a threshold
8. Crossing zero
9. Remaining above zero
10. Remaining below zero
11. Remaining within a range
12. Breaking out of a range
13. Returning to a previous value
14. Reaching a new high
15. Reaching a new low
16. Nearing an extreme value
17. Saturation / approaching a maximum or minimum
18. Oscillating within a bounded range

## 2. Rate and momentum behaviours
19. Increasing rate of rise
20. Decreasing rate of rise
21. Increasing rate of fall
22. Decreasing rate of fall
23. Acceleration
24. Deceleration
25. Momentum strengthening
26. Momentum weakening
27. Momentum reversal
28. Sudden spike
29. Sudden drop
30. Gradual buildup
31. Rapid movement after a quiet period
32. Momentum exhaustion
33. Delayed response
34. Momentum persistence

## 3. Turning-point and reversal behaviours
35. Local peak
36. Local trough
37. Higher high
38. Lower high
39. Higher low
40. Lower low
41. Peak formation
42. Trough formation
43. Peak weakening
44. Trough strengthening
45. Reversal after an extended rise
46. Reversal after an extended fall
47. Failed reversal
48. Reversal confirmation
49. Repeated rejection near a level
50. Repeated bounce near a level
51. V-shaped reversal
52. Inverted-V reversal
53. Rounded reversal
54. Double top
55. Double bottom

## 4. Threshold and state behaviours
56. Entering an overbought zone
57. Leaving an overbought zone
58. Entering an oversold zone
59. Leaving an oversold zone
60. Remaining in an extreme zone
61. Repeated threshold crossings
62. False breakout of a threshold
63. Reclaiming a threshold
64. Losing a threshold
65. State persistence
66. State flip
67. Rapid state flipping
68. State stabilization
69. Transition from weak to strong
70. Transition from strong to weak

## 5. Multi-component indicator behaviours
71. Components converging
72. Components diverging
73. Bullish crossover
74. Bearish crossover
75. Crossover approaching
76. Crossover followed by separation
77. Separation increasing
78. Separation decreasing
79. Components moving in the same direction
80. Components moving in opposite directions
81. One component leading another
82. One component lagging another
83. Component crossover failure
84. Component order reversal
85. Histogram expansion
86. Histogram contraction
87. Histogram sign change

## 6. Price-relative behaviours
88. Price approaching an indicator line
89. Price moving away from an indicator line
90. Price crossing an indicator line upward
91. Price crossing an indicator line downward
92. Price repeatedly crossing an indicator line
93. Price remaining above an indicator line
94. Price remaining below an indicator line
95. Price touching and rejecting a line
96. Price touching and bouncing from a line
97. Price and indicator moving together
98. Price and indicator moving in opposite directions
99. Price making a new high while the indicator does not
100. Price making a new low while the indicator does not
101. Price-indicator divergence
102. Price-indicator convergence

## 7. Volatility and range behaviours
103. Volatility expansion
104. Volatility contraction
105. Volatility spike
106. Volatility normalization after a spike
107. Range compression
108. Range expansion
109. Squeeze formation
110. Breakout after compression
111. Expansion losing strength
112. Volatility rising while momentum weakens
113. Volatility falling while momentum strengthens

## 8. Repetition and temporal behaviours
114. Consecutive rises
115. Consecutive falls
116. Alternating rises and falls
117. Repeated weakening
118. Repeated strengthening
119. Behaviour persisting for N minutes
120. Behaviour appearing for the first time
121. Behaviour disappearing
122. Behaviour recurring after a gap
123. Increasing frequency of a behaviour
124. Decreasing frequency of a behaviour
125. Repeated pattern with similar magnitude
126. Repeated pattern with diminishing magnitude
127. Repeated pattern with increasing magnitude
128. Behaviour following a specific sequence of states

## 9. Multi-timeframe behaviours
129. Short and long timeframes agreeing
130. Short and long timeframes disagreeing
131. Short timeframe reversing while long timeframe remains stable
132. Short timeframe reversing while long timeframe strengthens
133. Short timeframe leading a long-timeframe reversal
134. Long timeframe weakening before short-timeframe reversal
135. Timeframes converging toward the same direction
136. Timeframes diverging in direction
137. Higher-timeframe trend with lower-timeframe pullback
138. Lower-timeframe breakout against higher-timeframe trend
139. Multiple timeframes changing direction together
140. Timeframe-specific momentum exhaustion
141. Behaviour appearing on smaller timeframes before larger timeframes
142. Higher-timeframe signal strengthening while lower-timeframe signal weakens

## 10. Cross-indicator behaviours
143. Multiple indicators rising together
144. Multiple indicators falling together
145. Indicators confirming the same direction
146. Indicators contradicting each other
147. One indicator reversing before another
148. One indicator confirming another after a delay
149. Momentum weakening while trend strength increases
150. Momentum strengthening while trend strength decreases
151. Price rising while momentum indicators weaken
152. Price falling while momentum indicators strengthen
153. Multiple indicators approaching extreme levels together
154. Multiple indicators reversing together
155. One indicator diverging from a group of indicators
156. Indicator agreement increasing
157. Indicator agreement decreasing
158. A specific indicator combination appearing before a zone

## 11. Volume and directional confirmation behaviours
159. Price movement confirmed by volume
160. Price movement without volume confirmation
161. Volume increasing while price movement weakens
162. Volume decreasing while price movement strengthens
163. Volume spike near a turning point
164. Directional dominance increasing
165. Directional dominance decreasing
166. Trend strength increasing without directional confirmation
167. Trend strength weakening despite persistent direction
168. Price and cumulative volume diverging

## 12. Pattern lifecycle behaviours
169. Early formation
170. Developing formation
171. Mature formation
172. Weakening formation
173. Failed formation
174. Confirmed formation
175. Formation followed by a reversal
176. Formation followed by continuation
177. Formation followed by a delayed reaction
178. Formation appearing shortly before a zone
179. Formation appearing during a zone
180. Formation recurring at similar distances before multiple zones

## Implementation notes

- Treat each behaviour as a candidate feature or rule template; do not generate every behaviour for every indicator blindly.
- Applicability depends on indicator type. Crossovers require related components; price-relative behaviours require a meaningful price reference.
- Define each behaviour mathematically before testing it. Terms such as “weakening,” “exhaustion,” and “confirmation” need explicit operational definitions.
- Use only information available at the prediction timestamp. A peak/trough requiring future bars cannot be used as an input feature before confirmation.
- Compare behaviour occurrence around target zones with eligible non-zone periods.
- Count distinct events and dates, not every adjacent minute as independent evidence.
- Test chronologically on unseen periods and check for redundant definitions.
- A behaviour remains a hypothesis until validation measures event coverage, false positives, lead time, and stability.
