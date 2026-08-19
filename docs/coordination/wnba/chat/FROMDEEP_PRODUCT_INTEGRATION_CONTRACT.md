# WNBA FromDeep Product Integration Contract

Status: **USER/CHAT AGREED PRODUCT SEMANTICS**

Date: 2026-08-19

This document clarifies the product role of WNBA FromDeep and is binding Prime strategy terminology for future FromDeep work.

## Core clarification

**FromDeep is not a slip family and it does not construct a slip.**

FromDeep produces **zero, one, or more qualified single-leg picks** on a slate.

Those single-leg FromDeep outputs exist as an optional **flex/add-on candidate surface** that may later be made available to the actual core slip-family construction process. The core Builder families remain responsible for constructing multi-leg slips.

Conceptually:

`FromDeep signal registry -> qualified single-leg picks (0..N) -> optional flex/add-on availability to core slip construction`

not:

`FromDeep -> multi-leg slip`.

## Independence

FromDeep remains scientifically independent of core 2L/3L/4L selected-leg depletion while its signal method is researched and evaluated.

Its later product integration may allow one or more qualified FromDeep single-leg picks to flex into or supplement an actual slip-family build, but that attachment/routing behavior is a separate downstream product decision. It is not part of current signal discovery unless explicitly authorized.

FromDeep does not need to output exactly one pick per market or exactly one pick per slate. Sparse output and complete abstention remain valid. Multiple qualified single-leg picks may coexist when the eventual frozen output policy permits them.

## Ranking semantics

Any current or future `rank-1` FromDeep result is a **diagnostic comparison only unless separately promoted into an output policy**.

The active SAFE historical-as-of viability mission may retain its predeclared probability rank-1 diagnostic because it helps compare the signal gate with existing model ordering, but that diagnostic:

- does not define FromDeep as a one-pick product;
- does not cap FromDeep at one pick per market/date or slate;
- does not discard the all-eligible single-leg surface;
- does not authorize a final output count/cap;
- does not construct a slip.

The scientifically primary action evidence remains the complete sealed set of eligible single-leg rows after GREEN eligibility and RED veto.

## Active-mission terminology amendment

For `WNBA_FROMDEEP_SAFE_HISTORICAL_ASOF_SIGNAL_VIABILITY_R1`:

- references to a future `slip-construction` decision must be read as a future **single-leg FromDeep output policy and optional attachment/flex integration decision**;
- references to a `FromDeep slip cap` mean a future **FromDeep single-leg output count/cap policy**, if one is ever adopted;
- the phrase `final multi-leg FromDeep slips` is invalid terminology and must not be implemented;
- the current mission must return eligible single-leg evidence and the rank-1 diagnostic separately, without treating rank-1 as the product output.

No other scientific method, SAFE/UNCERTAIN/EXCLUDED authority, GREEN/RED/GRAY gate, historical-as-of rule, protected-data boundary, or resource envelope is changed by this clarification.

## Downstream decision boundary

After causal FromDeep signal viability is known, Chat/user may separately decide:

1. which qualified single legs FromDeep should actually emit (zero, one, or more);
2. whether/how those emitted single-leg picks may be offered as optional flex/add-on choices to the actual slip families;
3. any per-slate, per-market, duplication, correlation, or portfolio constraints required for that integration.

Until then, signal discovery/evaluation must not silently invent those product-routing rules.
