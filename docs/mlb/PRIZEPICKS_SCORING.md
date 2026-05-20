# PrizePicks MLB Scoring Notes

Status: implementation reference  
Last updated: 2026-05-11

Source file: `PPMLBScoringChart.txt`

## Eligibility

Batter projection eligibility:

- batter must be in the starting lineup
- batter must record at least one plate appearance

Pitcher projection eligibility:

- pitcher must throw at least one pitch

Combo projection eligibility:

- every listed athlete must satisfy their own eligibility rule
- if one combo athlete is DNP, the whole combo square is DNP

First-inning projection eligibility:

- both listed starting pitchers must throw the first pitch in the inning
- first-inning runs/walks rules are special because settlement can be complete after the first inning

## DNP / Postponement Rules To Model

The settlement layer must track:

- game canceled
- game postponed
- game not started before the platform cutoff
- suspended game completion window
- official shortened game
- first-inning prop exception

These should be settlement rules, not model probability features.

## Reboot Rules To Model

Batter reboot risk matters for PrizePicks MLB.

Reference behavior:

- regular-season batter can be reboot-eligible after leaving with two or fewer plate appearances
- pitcher projections are not reboot-eligible under the current policy
- reboot applies to More selections only
- if the More projection is already passed before exit, the square can still win

The model should expose a `reboot_risk` flag for slip filtering and UI context.

## Hitter Fantasy Score

Use these scoring weights:

- single: `3`
- double: `5`
- triple: `8`
- home run: `10`
- run: `2`
- RBI: `2`
- walk: `2`
- hit by pitch: `2`
- stolen base: `5`

## Pitcher Fantasy Score

Use these scoring weights:

- win: `6`
- quality start: `4`
- earned run: `-3`
- strikeout: `3`
- out: `1`

## Market Coverage

Initial PrizePicks MLB board markets:

- hits
- singles
- doubles
- triples
- total bases
- hits + runs + RBIs
- runs
- RBIs
- home runs
- plate appearances
- walks
- stolen bases
- hitter strikeouts
- hitter fantasy score
- pitcher strikeouts
- pitching outs
- hits allowed
- earned runs allowed
- walks allowed
- pitches thrown
- pitcher fantasy score
- first-inning runs allowed
- first-inning walks allowed
- pitcher strikeouts combo
- pitcher strikeouts + total bases

## Settlement Notes

- Extra innings count for full-game projections.
- Official MLB scoring decisions drive settlement.
- Later stat corrections should not be assumed unless the platform issues a correction.
- Shortened official games can still score as usual.
- Team and Culture Picks may follow different rules and should not be mixed into player prop settlement.
