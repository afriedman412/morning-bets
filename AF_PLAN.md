**THE PLAN**  
Model baseball games as accurately as possible to make better bets on baseball games.

- We are probably not going to beat the books AT SCALE, and we are probably building the same model with the same logic that they and everyone else is  
- We can, however:  
  - Manually price shop (Kalshi – the easiest number for us to get mechanically – has it at \-150 but we can get it at \-110 somewhere else? Great\!)  
  - Road test capper logic (“this pitcher smokes lefties, take his K prop” … we can actually evaluate those statements, at least qualitatively)

**THE APPROACH**  
Accurately simulate baseball games measured by their outcomes, and then infer everything else (props especially, but maybe also game script?) from that.

**ROUGH HIERARCHY OF IMPORTANCE**

1. Pitching (most consistent piece … \~3 pitchers per team v. \~9 hitters per team)  
   1. Use (how long does a given pitcher stay in the game)  
      1. Starting pitching (⅔ of the pitching, assuming \~6 innings pitched)  
         1. How long does the starter stay in?  
            1. Performance  
               1. Earned runs  
               2. Baserunners allowed  
            2. Pitch count (pitcher specific)  
            3. Manager tendency  
            4. Bullpen condition  
      2. Bullpen  
         1. How long does each reliever stay in?  
            1. Situation (long reliever might be there for 3 innings, LOOGY might be there for 1 out)  
               1. Opposing sides need to be simulated in tandem in order to consider team score  
            2. Performance  
               1. Earned runs  
               2. Baserunners allowed  
            3. Pitch count / Fatigue (relievers are more sensitive, these are kind of equivalent)  
            4. Manager tendency (some managers are more surgical w their bullpens)  
   2. Variables  
      1. Road/Home  
      2. day/night  
      3. Team status (early in the season? Late with no playoff hopes?)  
      4. Pitcher status (hot prospect being handled with kid gloves? Veteran eating innings for a lost season?)  
   3. Matchup  
      1. Opponent (do they run a lot? Small ball or big sluggers?)  
      2. Individual hitter (in the weeds here, but this is probably the extent to which we need to consider individual hitters … I don’t think there’s a lot to be gained by predicting things from a pitcher-agnostic hitting context)

**THE TARGETS**

1. First 5 innings team total (isolates starting pitcher)  
2. First 7 innings team toal (minimal bullpen exposure)  
3. Final score (full bullpen exposure)

