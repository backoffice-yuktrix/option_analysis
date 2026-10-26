i missed to include

based on rough draft phases:

after Phase 3 Compute the indicator (all timeframes, lag, seq, day flags)
Phase 4 Behaviours  - we use this "analysis_rajkumarn/Trading_indicator_categories.md" to first list down  what kind of columns from Base Indicator values needed and using python we generate them; also based on these new columns - we will refine the "analysis_rajkumarn/Trading_indicator_behaviours_catalogue.md" to Current_ind_behav_catalogue.md with an example of showing how it might happen
rough estimate of total columns (considering only OHLC) - for each row in 1 minute timestamp
32 - (OHLC value 4 * 8 time frame 1/2/3/5/8/13/21/34)
8 - (for single value in an indicator at each time frame 1/2/3/5/8/13/21/34)
72 - (1/2/3/5 - 9 lag value, 9 seq value per time frame - 18, 18*4=72) (just confirm based on our previous discussion)
24 - (8/13/21/34 - 3 lag value, 3 seq value per time frame - 6, 6*4=24) (just confirm based on our previous discussion)
~ 140 columns and when creating columns for behavioural analysis - it might exponentially increase from 300 to 500

Phase 5 LLM discovery on a sample of 10 zones - if there is 100 hill zone, then we generate atleast 100 set  - each set is a random 10 zone - ask LLM to generate condition for indicator behaviour for each set and then ask another LLM them to consolidate and pick top 10 to 15 (reducing redundancy based on condition wordings) - and then generate python code for each condition and checking 2 (1. how good LLM actually said - for ex: I gave zone1 to zone10 - it said this condition applied on zone1, zone3, zone5,zone6 - using python will check on these zone it worked, in other zone it not worked - so first level - it conveyed correctly ; 2. then apply this in other rest of zone - to make sure this is decent valuable condition)

and while running LLM on each set - we provide subset (not complete list) of Current_ind_behav_catalogue.md so LLM might have an idea of how to see it
in this each set - same like exposing only 10 zone, we will expose only few column (as LLM at decent efficiency, can handle only 150 rows x approx 100 columns and we might filter columns based on subset provided in Current_ind_behav_catalogue.md)


summaried flow:
2. Phase 2 Events and zones - changes - 2.7 Zones and Events - candles_events.parquet - Zone of "valley 10:00" - instead we give ZoneID
3. Phase 3 Compute the indicator (all timeframes, lag, seq, day flags) [using candles_events.parquet - create a copy and proceed, and save it after Phase 4]
4. Phase 4 Behaviours
	4.1. (subagent) using LLM with analysis_rajkumarn/Trading_indicator_categories.md and Indicator calc - generating behavioural columns list and its calculation
	4.2. creating python and creating columns and save candles_events_$Indicator$.parquet
	4.3. (subagent) refine the "analysis_rajkumarn/Trading_indicator_behaviours_catalogue.md" to Current_ind_behav_catalogue.md using behavioural columns list (and its calc)
5. Phase 5 LLM discovery on a sample of 10 zones
	5.1. based on Phase 2, 3, 4 - work log or create python - to figure out count - hill, valley zone and indicator columns (base and behavioural) and ZoneIDs list (candles_events_$Indicator$.parquet) [running 5.2 to 5.8 for hill once and valley once]
	5.2. (subagent) - using ZoneIDs list, Current_ind_behav_catalogue.md - create each subset ZoneID and columns - structured output
	5.3. using python and candles_events_$Indicator$.parquet create candles_events_$Indicator$_set$n$.parquet for each set
	5.4. (subagent) - (this runs for each set) (for each set - A main subagent owns this set [it doesnt see candles_events_$Indicator$_set$n$.parquet, just orchestrates] and first its runs its children - 2 subagent for basic analysis and difficulty (2 subagent so even if one misses, another finds) (difficulty - if it needs a column calc - like instead of LLM seeing that value directly, it can ask to calc new column(s) and based on that it can see it again - this new column(s) - can help to see pattern better) (initial 2 times and asking new columns - based on 1st and 2nd subagent - it can consolidate both results and new column(s) - and only if new column(s) - create python, run on candles_events_$Indicator$_set$n$.parquet to candles_events_$Indicator$_set$n$_v2.parquet and now run 3rd and 4th subagent and repeat once more (5th and 6th)) (so it will run subagent in pair - 3 rounds, 1 must, 2nd and 3rd row - depends) (now consolidate it and formulate final condition) (create python file and run on candles_events_$Indicator$_set$n$.parquet and check zone it said and zone not said - to compare LLM saw and actual finding matches) (if what LLM saw and python output match then proceed, else just check python code and if logic error in python - correct it, else report it and stop, also do this only 1 time, dont stuff there) (then run on candles_events_$Indicator$.parquet to see in zone and non zone) )
	5.5. (subagent) consolidate all subset outputs (it also uses Current_ind_behav_catalogue.md, columns list (with calc)) - and final consolidation and reduce redundancy
	5.6. using - python for final reduced condition - and creating a structured output row - each zone , columns - condition, values - condition able to predict that zone
	5.7. (subagent) uses 5.6 output and see combining the condition
	5.8. create python for final single condition of that indicator and check in training dataset - to see in zone and non zone places and create a short numerical report
	
	
	
4.1, 5.2,... - these are my understanding used to convey steps to you, can change it accordingly
subagent - create prompts now naming Approach_Steps_SubAgent_$Functionality$.md 