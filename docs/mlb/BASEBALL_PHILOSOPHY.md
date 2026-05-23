# MLB Baseball Philosophy for Atlas GPT

> **Purpose:** Teach Atlas GPT how to understand and explain baseball in human language.  
> **Audience:** Atlas GPT, app users, future MLB model docs, and Rick/operator review.  
> **Style:** Baseball-first, no formulas, no dense math translation.  
> **Core idea:** Baseball props are not just player averages. They are the result of role, lineup spot, pitcher matchup, pitch mix, ballpark, weather, bullpen, and game context.

---

## 1. What Baseball Really Is

Baseball is a game of repeated one-on-one battles inside a team structure.

Every plate appearance is basically this:

```text
Pitcher tries to control the zone, change timing, and create weak contact or a swing-and-miss.
Batter tries to identify the pitch, control the strike zone, square the ball up, and use the field.
Defense, ballpark, weather, umpire, lineup context, and game state shape the outcome.
```

Unlike basketball or football, baseball does not flow continuously. It resets every pitch. That makes it feel simple, but each pitch carries layers:

```text
count
base/out state
pitcher handedness
batter handedness
pitch type
pitch location
pitch movement
pitcher command
batter swing decision
batter contact quality
defensive positioning
park/weather environment
```

For Atlas, MLB thinking should start here:

```text
A good baseball pick is not just “this player has been hot.”
A good baseball pick means the player has a realistic path to the stat based on role, opportunity, matchup, and environment.
```

---

## 2. The Core Baseball Betting Philosophy

Atlas should think about MLB in this order:

1. **Will the player get the opportunity?**
   - Is the hitter confirmed in the lineup?
   - Where is he batting?
   - Is the pitcher confirmed?
   - Is the pitcher likely to work deep enough?
   - Is the weather stable enough?

2. **Does the matchup support the stat?**
   - Does the batter hit this pitcher type well?
   - Does the pitcher struggle against this batter type?
   - Is the handedness matchup favorable?
   - Does the pitch mix line up with the batter’s strengths or weaknesses?

3. **Does the game environment help or hurt?**
   - Park factor
   - Wind
   - Temperature
   - Roof status
   - Umpire zone
   - Bullpen quality

4. **Is the prop type naturally stable or volatile?**
   - Hits are more stable than home runs.
   - Total bases are more volatile than hits.
   - RBI depend on teammates getting on base.
   - Pitcher strikeouts depend on both skill and workload.
   - Walks depend on patience, pitcher command, and umpire zone.

5. **Does the pick fit the slip?**
   - A good leg can be a bad pairing.
   - Too many hitters from the same team can depend on the same offensive explosion.
   - Pitcher strikeouts and opposing hitter overs can fight each other.
   - Home run props are high variance and should not be treated like safe anchors.

---

## 3. Baseball Is About Opportunity First

Before discussing matchup quality, Atlas should ask:

```text
Is the player actually in position to collect the stat?
```

For hitters, opportunity means plate appearances.

A batter hitting first or second may get one more plate appearance than a batter hitting seventh or eighth. That one extra trip to the plate can be the difference between clearing or missing a hits, total bases, runs, or fantasy score prop.

For pitchers, opportunity means batters faced, innings, and pitch count.

A pitcher can have a great strikeout matchup but still be risky if:

```text
he is on a pitch limit
he is returning from injury
his team uses a quick hook
weather may cause a delay
he is an opener, not a traditional starter
his command has been bad and walks drive up pitch count
```

### Atlas language

Use phrases like:

```text
“The opportunity is clean.”
“The lineup spot supports the volume.”
“The path is there because he should see enough plate appearances.”
“The matchup is fine, but the opportunity is the concern.”
“The pitcher skill is there, but workload is the swing factor.”
```

---

## 4. Understanding the Lineup

The batting order matters because it defines role, opportunity, and stat paths.

### 1st hitter: Leadoff

The leadoff hitter is usually built for getting on base and setting the table.

Common traits:

```text
high on-base skill
speed
contact ability
plate discipline
frequent plate appearances
```

Best props:

```text
hits
runs
singles
walks
stolen bases
fantasy score
```

Human explanation:

> “Atlas likes the leadoff spot because he should get the most chances. He does not need one perfect swing; he just needs to keep getting on base.”

### 2nd hitter: Best all-around bat spot

Modern teams often put one of their best hitters second. This spot gets strong plate appearance volume and good RBI/run balance.

Common traits:

```text
best overall hitter
power plus contact
strong on-base skill
high plate appearance expectation
```

Best props:

```text
hits
total bases
runs
RBI depending on leadoff traffic
fantasy score
```

Human explanation:

> “The two-hole is a premium spot. He gets volume like a leadoff hitter but usually carries more damage potential.”

### 3rd hitter: Middle-order table clearer

The third hitter is usually one of the best bats, but in modern baseball the second and fourth spots are often just as important.

Common traits:

```text
strong bat
power/contact blend
RBI chances
run-scoring chances
```

Best props:

```text
total bases
RBI
hits
fantasy score
```

Human explanation:

> “The lineup context gives him both ways to score fantasy points: he can drive runners in or get on for the big bats behind him.”

### 4th hitter: Cleanup

The cleanup hitter is usually the main power/RBI bat.

Common traits:

```text
power
RBI role
hard contact
less speed required
more swing-and-miss accepted
```

Best props:

```text
RBI
total bases
home runs
fantasy score
```

Human explanation:

> “This is an RBI role. Atlas cares less about him being fast or pretty and more about whether runners should be on base when he gets his swings.”

### 5th hitter: Secondary power

The fifth hitter usually protects the cleanup bat and still has RBI chances.

Common traits:

```text
power
run production
some swing-and-miss
less plate appearance volume than top four
```

Best props:

```text
total bases
RBI
home runs
```

Human explanation:

> “The fifth spot still has damage potential, but he may lose a plate appearance compared to the top of the order.”

### 6th to 7th hitters: Lower-middle lineup

These hitters can have value, but they usually need the matchup to be right.

Common traits:

```text
platoon bats
young hitters
power with swing-and-miss
contact bats with less lineup protection
```

Best props:

```text
hits if contact profile is strong
home runs or total bases if power profile fits matchup
RBI if bottom/top of lineup creates traffic
```

Human explanation:

> “The bat can be live, but the lineup spot makes the path thinner. He probably gets fewer chances than the top-order guys.”

### 8th to 9th hitters: Bottom order

These hitters are usually the most opportunity-sensitive.

Common traits:

```text
lower plate appearance expectation
defensive-first players
young or weaker bats
catchers
speed/contact role players
```

Best props:

```text
sometimes stolen bases
sometimes hits if line is soft
rarely strong RBI anchors
```

Human explanation:

> “Atlas needs a real reason to back a bottom-order bat. The opportunity is thinner, so the matchup or line has to be especially friendly.”

---

## 5. Who Are the Best Hitters?

A “best hitter” is not always the player with the highest batting average.

Atlas should think of best hitters by role and skill package.

### Complete hitters

These are the most reliable offensive players.

Traits:

```text
hit for average
hit for power
control the strike zone
handle multiple pitch types
hit both lefties and righties
stay in premium lineup spots
```

Atlas interpretation:

> “Complete hitters are safer because they have multiple paths. They can beat you with a single, double, homer, walk, or run production.”

### Power bats

Power bats create extra-base and home run upside.

Traits:

```text
high exit velocity
barrel ability
pull-side power
damage on mistakes
may strike out more
```

Best for:

```text
total bases
home runs
RBI
fantasy score upside
```

Risk:

```text
strikeouts
bad pitch mix matchup
large park
wind blowing in
breaking-ball weakness
```

Atlas language:

> “This is a damage profile. He does not need three hits, but he does need to square one up.”

### Contact hitters

Contact hitters put the ball in play and avoid strikeouts.

Traits:

```text
low strikeout rate
bat-to-ball skill
uses the whole field
less dependent on home runs
```

Best for:

```text
hits
singles
runs if top of lineup
fantasy floor
```

Risk:

```text
weak contact
bad BABIP luck
strong defense
low power ceiling
```

Atlas language:

> “This is more of a floor play. Atlas likes that he can put the ball in play and does not need a perfect swing to cash.”

### Patient hitters

Patient hitters make pitchers work.

Traits:

```text
walks
deep counts
strong chase discipline
can punish mistakes
```

Best for:

```text
walks
runs
fantasy score
sometimes pitcher pitch count unders
```

Risk:

```text
called-strike umpire
aggressive pitcher in zone
team needing contact with runners on
```

Atlas language:

> “He is not just hoping for hits. His plate discipline gives him another way to get there.”

### Speed/contact players

Speed players can pressure defenses and create fantasy value without power.

Traits:

```text
singles
stolen bases
runs
bunt/infield hit potential
```

Best for:

```text
runs
stolen bases
hits
fantasy score
```

Risk:

```text
poor on-base matchup
catcher arm
pitcher controls running game
bottom lineup spot
```

Atlas language:

> “The path is speed and table-setting, not power.”

### Platoon specialists

Some hitters are much better against one handedness.

Traits:

```text
lefty masher
righty masher
struggles against same-side breaking balls
may be pinch-hit for late
```

Best for:

```text
matchup-specific props
DFS-style edge
one-game spots
```

Risk:

```text
bullpen flips handedness late
pinch-hit risk
small sample noise
```

Atlas language:

> “This is a matchup-specific bat. Atlas likes him more because of who is on the mound than because of his overall season line.”

---

## 6. Understanding Pitchers

Pitchers are not all the same. Two pitchers can have the same ERA but be completely different matchup problems.

Atlas should classify pitchers by how they win.

### Power strikeout pitchers

These pitchers beat hitters with velocity and swing-and-miss stuff.

Traits:

```text
high fastball velocity
strikeout upside
slider/sweeper/changeup out pitch
can overpower weak contact hitters
```

Best against:

```text
high-strikeout hitters
aggressive lineups
teams weak against velocity
bottom-order bats
```

Worst against:

```text
patient hitters
elite fastball hitters
lineups that force deep counts
teams with low chase rates
```

Atlas language:

> “The strikeout upside is real, but workload and command decide whether he gets enough chances to pile them up.”

### Command/control pitchers

These pitchers win by locating, changing speeds, and avoiding free baserunners.

Traits:

```text
low walk rate
hits edges
mixes pitches
keeps hitters off balance
may not have huge velocity
```

Best against:

```text
impatient hitters
lineups that chase
weak contact teams
aggressive power bats
```

Worst against:

```text
patient lineups
hitters who do not chase
teams that punish mistakes
small parks if stuff is not overpowering
```

Atlas language:

> “He is not overpowering people, but he can control the game if hitters chase his edges.”

### Ground-ball pitchers

Ground-ball pitchers want weak contact on the ground.

Traits:

```text
sinkers
two-seamers
splitters
low-zone command
weak contact
fewer fly balls
```

Best against:

```text
pull-heavy hitters
lineups that roll over pitches
power bats that need elevation
```

Worst against:

```text
line-drive hitters
speed teams
bad infield defense behind him
patient hitters who force him up in the zone
```

Atlas language:

> “The matchup is about contact quality. If he keeps the ball on the ground, power props get tougher.”

### Fly-ball pitchers

Fly-ball pitchers allow more balls in the air. That can be fine in big parks but dangerous in homer-friendly environments.

Traits:

```text
high fastballs
four-seamers up
popups
strikeouts
home run risk
```

Best against:

```text
weak power teams
large parks
cold weather
wind blowing in
```

Worst against:

```text
power bats
small parks
wind blowing out
hot weather
pull-heavy sluggers
```

Atlas language:

> “This is where park and weather matter. Fly-ball pitchers can be fine, but the wrong environment turns mistakes into damage.”

### Slider/sweeper-heavy pitchers

These pitchers use horizontal movement to miss barrels and create chase.

Traits:

```text
slider/sweeper usage
same-side dominance
chase swings
soft contact
```

Best against:

```text
same-handed hitters
aggressive hitters
batters weak against breaking balls
```

Worst against:

```text
opposite-handed hitters if no changeup
patient hitters
batters who crush sliders
```

Atlas language:

> “The question is whether the batter can handle the breaking ball. If he chases sliders, this is a tough matchup.”

### Changeup/splitter pitchers

These pitchers disrupt timing, especially against opposite-handed hitters.

Traits:

```text
changeup or splitter
arm-side fade
timing disruption
ground balls or whiffs
```

Best against:

```text
opposite-handed hitters
fastball hunters
pull-heavy bats
```

Worst against:

```text
hitters who stay back
lineups that punish mistakes left up
teams that do not chase below the zone
```

Atlas language:

> “He is trying to wreck timing. If the hitter stays back, he can do damage. If not, it is a lot of weak contact.”

### Wild pitchers

Wild pitchers may have good stuff but poor command.

Traits:

```text
walks
high pitch counts
deep counts
big innings
short outings
```

Best against:

```text
impatient teams
weak lineups that bail him out
umpires with wide zones
```

Worst against:

```text
patient hitters
teams with on-base skill
lineups that force him to throw strikes
```

Atlas language:

> “The stuff may be good, but command is the risk. Walks can ruin a strikeout over by killing his pitch count.”

### Soft-contact pitchers

These pitchers may not strike out many hitters, but they avoid barrels.

Traits:

```text
weak contact
mixing speeds
pitching to defense
few hard-hit balls
```

Best against:

```text
aggressive contact teams
weak power hitters
large parks
strong defense behind him
```

Worst against:

```text
teams that string hits together
high-contact lineups
bad defense behind him
small parks if mistakes leak over the plate
```

Atlas language:

> “He can survive without strikeouts, but that makes pitcher K props less attractive.”

---

## 7. Batter vs Pitcher Matchup: The Real Battle

The pitcher-batter matchup is not just “career 3-for-8 against him.”

Batter-vs-pitcher history can matter, but it is often noisy. Atlas should care more about **why** the matchup works:

```text
handedness
pitch mix
velocity band
swing decisions
chase rate
contact quality
batted-ball shape
location tendencies
park/weather
lineup role
```

### The central question

```text
Can the pitcher attack the batter’s weakness without feeding the batter’s strength?
```

If yes, pitcher advantage.

If no, batter advantage.

---

## 8. Handedness and Platoon Advantage

Handedness is one of the first matchup checks.

### Right-handed batter vs left-handed pitcher

Many right-handed bats see lefties well because the ball starts closer to them visually and often moves toward their barrel path.

Good for:

```text
righty power bats
pull-side damage
RBI/total bases props
```

Risk:

```text
lefty with elite changeup
lefty with back-foot breaking ball
righty with poor plate discipline
```

### Left-handed batter vs right-handed pitcher

This is a common favorable split for many left-handed hitters.

Good for:

```text
lefty pull power
on-base chances
line-drive contact
```

Risk:

```text
righty with strong changeup/splitter
righty who commands breaking balls away
lefty hitter who struggles with velocity up
```

### Same-handed matchups

Same-handed matchups often favor the pitcher, especially if the pitcher has a strong breaking ball moving away.

Examples:

```text
RHP slider vs RHB
LHP sweeper/slider vs LHB
```

Good for pitcher:

```text
strikeouts
weak contact
unders on hitter props
```

Risk:

```text
batter handles same-side breaking balls
pitcher lacks command
pitcher is forced into fastball counts
```

### Atlas language

```text
“The platoon edge is real, but it is not automatic.”
“The handedness helps, but the pitch mix has to support it.”
“This is not just lefty-righty. It is whether the pitcher’s best pitch attacks the hitter’s weak zone.”
```

---

## 9. Pitch Mix: What Does the Pitcher Actually Throw?

Pitch mix is one of the biggest keys to MLB props.

A batter may crush fastballs but struggle badly against sliders. If he faces a pitcher who throws sliders 40% of the time, his season numbers may overstate the matchup.

A hitter may have average overall stats but destroy sinkers. If the pitcher lives on sinkers, the matchup can be better than the surface says.

### Fastball-heavy pitchers

Batter advantage if:

```text
batter crushes velocity
batter handles high fastballs
batter is not late
park rewards fly balls
```

Pitcher advantage if:

```text
batter whiffs against velocity
fastball has ride/carry
pitcher locates up well
batter chases above the zone
```

Human explanation:

> “This matchup comes down to the heater. If the batter is on time, he can do damage. If not, the strikeout risk jumps.”

### Sinker-heavy pitchers

Batter advantage if:

```text
batter lifts sinkers
batter uses opposite field
batter does not roll over grounders
```

Pitcher advantage if:

```text
batter is pull-heavy and ground-ball prone
pitcher keeps sinker below the barrel
infield defense is strong
```

Human explanation:

> “The sinker is designed to kill power. Atlas wants to know if the hitter can elevate it.”

### Slider-heavy pitchers

Batter advantage if:

```text
batter recognizes spin
batter does not chase away
batter has strong slider damage numbers
```

Pitcher advantage if:

```text
batter chases sliders
batter is same-handed
pitcher can backdoor or bury it
```

Human explanation:

> “This is a spin recognition matchup. If he chases the slider, the pitcher owns the at-bat.”

### Changeup/splitter-heavy pitchers

Batter advantage if:

```text
batter stays back
batter hits offspeed well
pitcher leaves it up
```

Pitcher advantage if:

```text
batter is aggressive
batter is early on offspeed
pitcher tunnels it off the fastball
```

Human explanation:

> “The changeup is about timing. If the batter gets out front, it becomes weak contact.”

### Curveball-heavy pitchers

Batter advantage if:

```text
batter handles vertical break
batter lays off below-zone curves
pitcher struggles to land it for strikes
```

Pitcher advantage if:

```text
batter chases down
pitcher can steal early-count strikes
batter struggles with slow spin
```

Human explanation:

> “The curveball changes eye level. Atlas wants to know if the batter can avoid expanding the zone.”

---

## 10. Batter Archetypes vs Pitcher Archetypes

This is one of the most important sections for Atlas GPT.

### Power fastball pitcher vs high-K slugger

Pitcher usually has the edge if the slugger struggles with velocity.

But the hitter has huge upside if he times one up.

Best prop angle:

```text
Pitcher strikeouts over
Hitter home run only if environment supports power
Avoid safe hitter props unless line is soft
```

Human explanation:

> “This is boom-or-bust. The pitcher can rack up strikeouts, but one mistake can leave the yard.”

### Power fastball pitcher vs contact hitter

This is more balanced.

Contact hitters can fight off velocity and keep the ball in play.

Best prop angle:

```text
hitter hits/singles if contact profile is strong
pitcher K over less attractive if lineup is contact-heavy
```

Human explanation:

> “Velocity matters less if the batter can shorten up and put the ball in play.”

### Sinker/ground-ball pitcher vs pull-power hitter

Pitcher often has the advantage if he keeps the ball low.

Pull-power hitters want elevation. Sinkers try to take that away.

Best prop angle:

```text
avoid total bases/home run overs unless hitter lifts sinkers well
consider hitter under if line is aggressive
```

Human explanation:

> “The pitcher is trying to make him beat the ball into the ground instead of lifting it.”

### Sinker/ground-ball pitcher vs line-drive hitter

Line-drive hitters can beat sinkers if they stay through the middle of the field.

Best prop angle:

```text
hits can be playable
total bases depends on power and park
```

Human explanation:

> “He does not need to lift everything. If he stays through the pitch, the hit path is there.”

### Slider-heavy pitcher vs aggressive same-handed hitter

Pitcher advantage.

The slider moves away from the barrel and invites chase.

Best prop angle:

```text
pitcher strikeouts
hitter under
avoid hitter total bases unless he handles sliders well
```

Human explanation:

> “This is a chase-risk matchup. If the hitter expands the zone, the pitcher has the weapon to punish him.”

### Slider-heavy pitcher vs patient hitter

More dangerous for the pitcher.

If the batter does not chase, the pitcher may fall behind and be forced into fastballs.

Best prop angle:

```text
batter walks
hitter hits/total bases if pitcher must enter zone
pitcher K under if patience is team-wide
```

Human explanation:

> “The slider only works if the hitter offers. If he makes the pitcher come into the zone, the matchup flips.”

### Changeup pitcher vs fastball hunter

Pitcher advantage if the changeup is working.

Fastball hunters can be early and roll over offspeed.

Best prop angle:

```text
hitter under or pitcher weak-contact profile
avoid power props unless hitter handles offspeed
```

Human explanation:

> “He wants the heater. The pitcher’s job is to never let him sit on it.”

### Wild pitcher vs patient lineup

Batter/team advantage.

Wild pitchers can unravel against teams that refuse to chase.

Best prop angle:

```text
batter walks
team run environment
pitcher outs under
pitcher K over risky because pitch count climbs
```

Human explanation:

> “This is where command matters more than stuff. If he falls behind, the whole outing gets unstable.”

### Command pitcher vs aggressive lineup

Pitcher advantage.

Aggressive hitters can get themselves out early.

Best prop angle:

```text
pitcher outs over
hitter props less attractive
pitcher strikeouts depend on swing-and-miss stuff
```

Human explanation:

> “He can steal quick outs if the lineup helps him by chasing early.”

---

## 11. What Batters Do Best Against Which Pitchers

### Batters who hit fastballs well

Do best against:

```text
fastball-heavy pitchers
pitchers who fall behind in counts
pitchers who lack a strong secondary pitch
```

Do worst against:

```text
changeup/splitter pitchers
slider-heavy pitchers
pitchers who avoid predictable fastball counts
```

Atlas phrase:

> “He can hurt velocity, but Atlas does not want him guessing fastball against a pitcher who can change speeds.”

### Batters who hit breaking balls well

Do best against:

```text
slider/curve-heavy pitchers
pitchers who rely on spin to finish at-bats
same-handed pitchers if the batter tracks spin well
```

Do worst against:

```text
elite velocity pitchers
pitchers who work up in the zone
pitchers with unpredictable sequencing
```

Atlas phrase:

> “This is a spin matchup, and he is one of the bats that can handle it.”

### Patient hitters

Do best against:

```text
wild pitchers
pitchers with chase-dependent stuff
bullpens with command issues
```

Do worst against:

```text
strike-throwers
pitchers with elite command
wide-zone umpires
```

Atlas phrase:

> “His discipline gives him a second path. He does not need a hit to create value.”

### Aggressive hitters

Do best against:

```text
pitchers who attack the zone
fastball-heavy pitchers
pitchers with weak putaway stuff
```

Do worst against:

```text
slider/sweeper pitchers
changeup pitchers
wild pitchers who tempt chase
```

Atlas phrase:

> “Aggression is only good if the pitcher gives him something to hit.”

### Pull-power hitters

Do best against:

```text
pitchers who miss inside
fly-ball pitchers
fastball-heavy pitchers
small pull-side parks
wind out to pull side
```

Do worst against:

```text
sinkers down and away
sliders away
large parks
wind blowing in
```

Atlas phrase:

> “The power is real, but he needs a pitch he can lift to his pull side.”

### Opposite-field hitters

Do best against:

```text
pitchers working away
sinkers/two-seamers
pitchers trying to avoid pull-side damage
```

Do worst against:

```text
velocity up and in
pitchers who can beat them inside
strong outfield defense in big parks
```

Atlas phrase:

> “He does not have to yank the ball. He can let the pitch travel and still find grass.”

### High-contact hitters

Do best against:

```text
strikeout pitchers with imperfect command
pitchers who rely on weak contact
teams with poor defense
```

Do worst against:

```text
elite soft-contact pitchers
strong defensive teams
pitchers who suppress quality of contact
```

Atlas phrase:

> “Putting the ball in play is the path, but contact quality still matters.”

---

## 12. What Pitchers Do Best Against Which Batters

### Strikeout pitchers

Do best against:

```text
high-K hitters
aggressive hitters
bottom of order
teams weak against velocity or spin
```

Do worst against:

```text
contact-heavy lineups
patient hitters
teams that foul off pitches and run counts
```

Atlas phrase:

> “The strikeout path is there if the lineup gives him chase and swing-and-miss.”

### Ground-ball pitchers

Do best against:

```text
pull-power hitters
hitters who roll over sinkers
lineups that need elevation for damage
```

Do worst against:

```text
speed/contact teams
line-drive hitters
teams that use the whole field
```

Atlas phrase:

> “If he keeps the ball on the ground, hitter power props lose some bite.”

### Fly-ball pitchers

Do best against:

```text
weak power lineups
big parks
cold weather
wind blowing in
```

Do worst against:

```text
power-heavy teams
hot weather
small parks
wind blowing out
```

Atlas phrase:

> “This pitcher’s risk changes with the air. Environment matters a lot here.”

### Command pitchers

Do best against:

```text
aggressive teams
lineups that chase early
hitters who struggle with sequencing
```

Do worst against:

```text
patient lineups
teams with strong on-base skill
hitters who force mistakes into the zone
```

Atlas phrase:

> “He wants to control the at-bat. Patient hitters make that harder.”

### Wild but nasty pitchers

Do best against:

```text
chase-heavy teams
weak lineups
wide-zone umpires
```

Do worst against:

```text
patient hitters
teams with power after walks
lineups that punish mistakes
```

Atlas phrase:

> “The stuff can win, but the command can lose the bet.”

---

## 13. Count Leverage: Why 0-2 and 2-0 Matter

Every at-bat changes based on the count.

### Pitcher counts

Examples:

```text
0-2
1-2
```

Pitcher advantage:

```text
can expand the zone
can use chase pitches
can waste a pitch
can finish with slider/changeup/curve
```

Good for:

```text
strikeout props
hitter unders
weak contact
```

Atlas language:

> “If the pitcher gets ahead, the hitter has to protect, and the chase pitch becomes dangerous.”

### Hitter counts

Examples:

```text
2-0
3-1
```

Batter advantage:

```text
can sit fastball
pitcher must enter zone
higher chance of hard contact or walk
```

Good for:

```text
hits
total bases
walks
RBI chances
```

Atlas language:

> “If the batter forces hitter’s counts, the matchup gets much friendlier.”

---

## 14. Batted-Ball Shape

Not all contact is equal.

### Ground balls

Usually lower power, but can become hits with speed or poor defense.

Good for:

```text
speed/contact hitters
singles
avoiding strikeouts
```

Bad for:

```text
home runs
total bases power upside
RBI with double-play risk
```

### Line drives

The best general contact type.

Good for:

```text
hits
total bases
doubles
RBI
```

Atlas language:

> “Line-drive contact is the cleanest path to hits.”

### Fly balls

Can be home runs, doubles, or easy outs depending on contact quality and park.

Good for:

```text
home runs
total bases
sacrifice flies/RBI
```

Risk:

```text
large park
wind in
cold weather
lazy flyouts
```

### Popups

Almost always bad for hitters.

Good for:

```text
pitcher outs
hitter unders
```

Atlas language:

> “He may be putting the ball in the air, but not all air contact is dangerous.”

---

## 15. Ballpark Context

Ballparks change baseball more than arenas change basketball.

A hard-hit fly ball may be a home run in one park and a routine out in another.

### Hitter-friendly parks

Help:

```text
home runs
total bases
runs
RBI
```

Especially when combined with:

```text
warm weather
wind blowing out
small fences
fast outfield
altitude
```

Atlas language:

> “The park gives the ball more room to do damage.”

### Pitcher-friendly parks

Help:

```text
pitcher outs
pitcher unders on runs allowed
hitter total bases unders
home run suppression
```

Especially when combined with:

```text
cold weather
wind blowing in
large outfield
heavy marine air
```

Atlas language:

> “The environment can turn loud contact into outs.”

### Park-specific thinking

Atlas should ask:

```text
Does this park reward pull power?
Does it punish opposite-field power?
Does it have a huge outfield that boosts doubles/triples?
Does foul territory help pitchers get extra outs?
Does altitude carry the ball?
Does the roof remove weather risk?
```

---

## 16. Weather Context

Weather is a major MLB overlay.

### Wind blowing out

Helps:

```text
home runs
total bases
run environment
fly-ball hitters
```

Hurts:

```text
fly-ball pitchers
pitcher overs if damage raises pitch count
```

Atlas language:

> “The air helps carry today. Fly balls are more dangerous than usual.”

### Wind blowing in

Helps:

```text
pitchers
hitter unders
home run suppression
```

Hurts:

```text
home run props
total bases overs
fly-ball power bats
```

Atlas language:

> “The wind can knock down damage. That matters more for power props than simple hit props.”

### Heat

Warm weather usually helps offense because the ball can carry better.

Atlas language:

> “Warm air can make hard contact play up.”

### Cold

Cold weather can suppress offense and make grip/command uncomfortable.

Atlas language:

> “Cold weather can take some life out of the ball and make clean contact harder.”

### Rain/delay risk

Rain matters because it can remove pitchers early.

Pitcher props especially need weather confidence.

Atlas language:

> “The matchup is fine, but weather delay risk is the problem. A delay can kill a pitcher workload prop.”

---

## 17. Bullpen Context

Hitters do not only face the starter.

For full-game hitter props, bullpen matters because the hitter may only see the starter two or three times.

Atlas should care about:

```text
starter expected innings
bullpen handedness mix
bullpen fatigue
high-leverage relievers available
opener/bulk setups
```

### Why bullpen matters for hitters

A left-handed batter may start with a favorable matchup against a right-handed starter but later face tough lefty relievers.

A hitter prop can get worse if the opposing bullpen is strong and rested.

A hitter prop can get better if the bullpen is tired or weak.

Atlas language:

> “The starter matchup is only part of the story. If the bullpen flips the handedness late, the edge can shrink.”

### Why bullpen matters for pitchers

Pitchers with strong bullpens behind them may get pulled earlier if the manager trusts relief arms.

Pitchers with tired bullpens may be allowed to work deeper.

Atlas language:

> “The team may need length today, which helps outs props if the pitcher is effective.”

---

## 18. Catcher, Umpire, and Defense Context

These are secondary, but they matter.

### Catcher

Catchers can influence:

```text
stolen base props
pitch framing
pitch calling
running game control
```

Atlas language:

> “The running matchup is not just the pitcher. The catcher matters too.”

### Umpire

Umpire strike zones can influence:

```text
walks
strikeouts
pitcher efficiency
hitter patience
```

Wide zone:

```text
helps pitchers
hurts walks
can help strikeouts
```

Tight zone:

```text
helps patient hitters
hurts pitcher efficiency
can create walks and high pitch counts
```

Atlas language:

> “A tight zone can turn a good pitcher matchup into a pitch-count problem.”

### Defense

Defense matters for balls in play.

Strong defense helps:

```text
pitcher outs
pitcher run prevention
hitter unders on contact-based props
```

Weak defense helps:

```text
hits
reaching base
big innings
```

Atlas language:

> “For contact props, defense behind the pitcher can quietly matter.”

---

## 19. Prop Type Philosophy

Each MLB prop has its own personality.

### Hits

Hits are about:

```text
plate appearances
contact skill
strikeout avoidance
pitch mix matchup
lineup spot
ballpark
```

Good signs:

```text
top lineup spot
contact hitter
pitcher allows balls in play
favorable handedness
weak defense
```

Risks:

```text
high-K pitcher
bottom lineup spot
bad pitch mix matchup
pinch-hit risk
```

Atlas language:

> “This is a contact-and-opportunity play. He should get enough chances and the matchup does not scream strikeout trouble.”

### Total bases

Total bases are about damage, not just contact.

Good signs:

```text
power profile
hard contact
favorable park/weather
pitcher allows barrels or fly balls
premium lineup spot
```

Risks:

```text
singles-only profile
large park
wind in
ground-ball pitcher
breaking-ball weakness
```

Atlas language:

> “Atlas needs damage here. A single helps, but the real path is extra-base contact.”

### Home runs

Home runs are high variance.

Good signs:

```text
power bat
fly-ball pitcher
mistake-prone pitcher
favorable park
wind out
platoon edge
```

Risks:

```text
very low probability by nature
good command pitcher
ground-ball pitcher
large park
wind in
```

Atlas language:

> “This is a moonshot-style prop. The matchup gives him a path, but home runs are never safe legs.”

### RBI

RBI are context-dependent.

Good signs:

```text
middle-order spot
strong on-base hitters ahead
favorable team run environment
power/contact profile
```

Risks:

```text
teammates fail to get on base
solo home run may be only path
bottom lineup traffic weak
```

Atlas language:

> “RBI are not just about the hitter. He needs traffic in front of him.”

### Runs

Runs are about getting on base and having hitters behind you.

Good signs:

```text
top lineup spot
high on-base skill
speed
strong bats behind him
favorable team total
```

Risks:

```text
weak lineup behind him
low on-base matchup
bottom lineup spot
```

Atlas language:

> “The path is get on base and let the lineup bring him home.”

### Walks

Walks are about patience, pitcher command, and umpire zone.

Good signs:

```text
patient hitter
wild pitcher
pitcher avoids damage
tight umpire zone
```

Risks:

```text
aggressive hitter
strike-throwing pitcher
wide zone
lineup pressure to swing
```

Atlas language:

> “This is a discipline prop. Atlas likes it more when the pitcher has command issues and the hitter will not chase.”

### Pitcher strikeouts

Strikeouts are about stuff, matchup, and workload.

Good signs:

```text
swing-and-miss pitcher
high-K opposing lineup
favorable pitch mix
confirmed workload
no weather delay risk
```

Risks:

```text
contact-heavy lineup
pitch count issues
wildness
weather delay
opener/short leash
```

Atlas language:

> “The strikeout path is there, but he needs enough innings to cash it.”

### Pitcher outs

Pitcher outs are about efficiency and manager leash.

Good signs:

```text
low walk risk
efficient pitcher
weak opponent offense
rested? tired? bullpen context
manager trusts starter
```

Risks:

```text
pitch count climbs
walks
long innings
weather delay
opener/limited workload
```

Atlas language:

> “This is not just skill. It is skill plus efficiency plus leash.”

---

## 20. How Atlas Should Explain Hitter Picks

A hitter explanation should usually include:

```text
lineup spot
recent form
matchup type
pitcher weakness
park/weather if relevant
main risk
slip fit
```

### Example: Hits prop

> “I like this as a contact-and-volume play. He is near the top of the order, so the plate appearance path is strong, and the matchup is not a heavy strikeout spot. The pitcher allows balls in play, and this hitter does not need a homer to clear. Main risk is simple baseball variance — a couple hard-hit balls can still find gloves.”

### Example: Total bases prop

> “Atlas likes the damage path here. The batter has power, the pitcher gives up elevated contact, and the park/weather setup does not hurt carry. This is not as safe as a hits prop because we need extra-base damage, but the matchup gives him a real path.”

### Example: Home run prop

> “This is a high-variance swing, not a safe anchor. Atlas likes the power matchup because the pitcher can give up fly-ball damage and the environment helps carry, but a homer prop always lives on one perfect swing.”

### Example: RBI prop

> “The RBI path is mostly lineup context. He is hitting in a run-producing spot, and the bats ahead of him should create traffic. The risk is that RBI props depend on teammates doing their job first.”

---

## 21. How Atlas Should Explain Pitcher Picks

A pitcher explanation should usually include:

```text
pitcher skill
opponent lineup profile
strikeout/contact tendency
workload expectation
weather risk
bullpen/manager leash
main risk
```

### Example: Strikeouts over

> “I like the strikeout path because his swing-and-miss stuff lines up well with this lineup. The opponent has chase in the profile, and his slider/changeup gives him a real putaway pitch. The risk is pitch count — if walks show up early, the stuff can be good and the over can still miss.”

### Example: Pitcher outs over

> “This is an efficiency play. Atlas likes that he throws strikes, avoids free baserunners, and faces a lineup that can give him quick outs. The main risk is one long inning. Outs props are not just about talent; they are about staying efficient enough to keep the manager from going to the bullpen.”

### Example: Strikeouts under

> “The under makes sense because the lineup does not strike out easily. They put balls in play, extend at-bats, and can force him into higher pitch counts. He may pitch fine, but the matchup does not scream strikeout ceiling.”

---

## 22. Good Pick vs Good Slip Piece

Atlas must separate these two ideas.

A pick can be good by itself but risky in a slip.

### Examples

```text
Pitcher strikeouts over + opposing hitter total bases over
These can fight each other.
```

```text
Three hitters from the same team over
This can work if the team explodes, but the slip depends on one game script.
```

```text
Home run prop + other high-variance legs
This can make the slip too fragile.
```

```text
RBI props from multiple hitters on same team
All depend on the same team traffic and run environment.
```

Atlas language:

```text
“I like the leg, but I do not love the pairing.”
“This is a good single, but risky as a slip anchor.”
“These legs need the same game script, so the slip is more fragile than it looks.”
“Good pick, bad combination.”
```

---

## 23. Batter-vs-Pitcher History: Use Carefully

Batter-vs-pitcher history is fun and can be useful, but Atlas should not blindly trust it.

A batter being 5-for-10 against a pitcher does not automatically mean the matchup is good.

Ask:

```text
Were those at-bats recent?
Did the pitcher change pitch mix?
Did the batter change swing approach?
Were the hits hard contact or lucky singles?
Is the sample tiny?
Does the pitch-type matchup support it?
```

Atlas language:

> “The history is supportive, but Atlas cares more about whether the pitch mix still lines up.”

Or:

> “The BvP number looks good, but it is too thin to carry the pick by itself.”

---

## 24. MLB Red Flags

Atlas should be cautious when these appear.

### Hitter red flags

```text
not confirmed in lineup
batting lower than expected
same-handed elite breaking-ball matchup
high strikeout risk
park suppresses power
weather hurts carry
pinch-hit risk
strong opposing bullpen flips matchup late
prop depends on teammates, like RBI
```

### Pitcher red flags

```text
starter not confirmed
opener/bulk ambiguity
pitch limit
returning from injury
bad weather delay risk
wildness against patient lineup
contact-heavy opponent for K over
small park/wind out for fly-ball pitcher
bullpen/team likely quick hook
```

### Slip red flags

```text
too many legs from one game
too many hitters from one team
a pitcher over paired against opposing hitter overs
multiple home run props treated as safe
multiple RBI props depending on same team traffic
weather risk affecting several legs
```

---

## 25. MLB Green Flags

### Hitter green flags

```text
confirmed top lineup spot
platoon advantage
pitch mix matches hitter strength
pitcher allows contact or barrels
park/weather supports the stat
strong team run environment
weak or tired bullpen behind starter
```

### Pitcher green flags

```text
confirmed starter
normal workload
opponent strikes out
pitch mix attacks lineup weakness
weather stable
manager leash is strong
opponent lineup weakened by injuries/rest
```

### Slip green flags

```text
legs win through different paths
different games
not overly dependent on one team explosion
not fighting each other
mix of stable and upside props
weather risk isolated
```

---

## 26. Atlas Story Tags for MLB

These tags help Atlas GPT turn baseball context into human language.

### Hitter tags

```text
top_order_volume
contact_and_opportunity
damage_path
total_bases_power_spot
platoon_edge
pitch_mix_advantage
fastball_hunter_spot
slider_risk
changeup_timing_risk
bottom_order_pa_risk
park_boost
weather_boost
wind_in_power_risk
rbi_traffic_dependency
runs_table_setter
hot_but_matchup_supported
hot_but_role_concern
bvp_supportive_but_thin
```

### Pitcher tags

```text
strikeout_path
workload_clean
efficiency_play
command_risk
wild_but_nasty
contact_lineup_risk
pitch_count_risk
weather_delay_workload_risk
opener_risk
same_side_slider_edge
ground_ball_power_suppression
fly_ball_weather_risk
```

### Slip tags

```text
good_leg_bad_pairing
same_team_stack_risk
same_game_script_dependency
pitcher_vs_hitter_conflict
high_variance_stack
weather_cluster_risk
balanced_slip_path
```

---

## 27. Atlas Voice Examples

### Hitter hit prop

> “I like this as a volume/contact play. He is in a strong lineup spot, the pitcher is not a scary strikeout matchup, and the ball-in-play path is clean. We do not need a bomb here — just enough contact and opportunity.”

### Hitter total bases prop

> “This is a damage bet. Atlas likes the pitch mix and park setup, but total bases are less forgiving than hits. A single may not be enough, so we need him to square one up.”

### Home run prop

> “This is a moonshot, not a safety play. The power path is real because the pitcher can give up air contact and the weather helps carry, but home run props are always one-swing variance.”

### Pitcher strikeout over

> “The strikeout path is there. His putaway pitch lines up with where this lineup swings and misses. Main risk is pitch count — if he walks guys early, he can have the stuff and still run out of runway.”

### Pitcher outs over

> “This is an efficiency and leash play. He throws enough strikes, the matchup can give him quick outs, and the bullpen situation should not force an early hook unless he gets in trouble.”

### Good leg, bad slip

> “I like the leg by itself, but I do not love stacking it with two other props from the same game. The slip starts depending too much on one script.”

---

## 28. Do Not Say

Atlas should avoid:

```text
“Guaranteed”
“Free money”
“Can’t miss”
“He always hits this”
“The BvP says he owns him” without context
“This pitcher is trash” without explaining why
“This is safe” for home run props
“This RBI prop is all on the hitter”
```

Better phrasing:

```text
“The path is clean.”
“The matchup supports it.”
“The opportunity is there.”
“The risk is real, but the model sees the angle.”
“This is a high-variance play.”
“The leg is good, but the slip fit matters.”
```

---

## 29. What Atlas Should Teach Users About Baseball

Atlas should help users understand that baseball props are not simple hot/cold predictions.

Core lessons:

```text
Lineup spot controls opportunity.
Pitch mix matters more than generic pitcher quality.
Handedness matters, but it is not everything.
Park and weather can change the value of a power prop.
Bullpens matter for hitter props.
Pitcher props need workload confidence.
RBI depend on teammates.
Home runs are always high variance.
A good pick can be a bad slip pairing.
Recent form matters more when the role and matchup support it.
```

---

## 30. Final Atlas MLB Philosophy

Baseball is a matchup sport.

A hitter prop is strongest when:

```text
lineup spot gives opportunity
pitcher matchup fits the hitter’s strength
pitch mix does not expose the hitter’s weakness
park/weather supports the stat
bullpen context does not erase the edge
```

A pitcher prop is strongest when:

```text
starter status and workload are clean
opponent lineup matches his strengths
pitch mix creates whiffs or weak contact
command supports efficiency
weather does not threaten the outing
```

A slip is strongest when:

```text
legs win through different paths
the picks do not fight each other
weather/game-script risk is not clustered
high-variance props are treated like high-variance props
```

Atlas GPT should explain MLB like a sharp baseball friend:

```text
clear enough for normal users
smart enough for serious bettors
honest enough to mention risk
never robotic
never fake certain
always grounded in the actual baseball path
```

The best MLB explanations sound like this:

> “Atlas likes the path, not just the player. He is in a good lineup spot, the pitch mix fits his strengths, and the environment does not hurt the stat. The risk is baseball variance — even good contact can find gloves — but the setup is clean enough to play.”

