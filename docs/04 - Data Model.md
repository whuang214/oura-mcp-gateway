# Data model

The API provides two related views of Oura data:

- Source-resource routes preserve granular facts using stable names and units.
- Curated analytics routes provide scalar, analysis-ready daily and weekly
  records without raw arrays or invented scores.

## Core rules

- Oura's returned `day` is the canonical calendar key.
- Timestamp offsets are preserved.
- Missing values remain null or absent; they are never converted to zero.
- A successful empty range returns `data: []`; it does not fabricate rows.
- Source IDs remain stable strings.
- Dense samples appear only on explicit sample routes.
- The current Oura day is `Provisional` because it can still change.

## Units

Source-resource routes use explicit canonical units:

| Measurement | Unit |
| --- | --- |
| Duration | integer seconds |
| Distance | meters |
| Temperature deviation | degrees Celsius |
| Heart rate | beats per minute |
| HRV | milliseconds |
| Calories | kilocalories, context only |

Curated analytics convert duration to hours or minutes where the field name
says so. Hours are rounded half-up to two decimals; event minutes are rounded
half-up to a whole minute; readable sleep duration uses `Xh Ym`.

## Coverage

Each requested resource has an independent outcome:

| Outcome | Meaning |
| --- | --- |
| `available` | One or more usable records returned |
| `empty` | Successful authoritative response with no records |
| `not_granted` | The Oura connection lacks the capability |
| `disabled` | Local policy disabled an optional resource |
| `error` | Authentication, validation, transport, timeout, or provider failure |

Sleep summary, contributing detailed sleep, readiness, and activity are core.
Other resources are supplemental.

| Daily status | Meaning |
| --- | --- |
| `Complete` | All core domains are usable |
| `Partial` | Some core data is usable and some is missing |
| `Provisional` | The current day has usable data that may change |
| `No Data` | A finalized date has no usable core data |
| `Sync Error` | A core retrieval failure prevented reliable ingestion |

`No Data` and `Sync Error` are visible through daily coverage. They do not
create empty daily-signal records. Supplemental failures cannot downgrade an
otherwise complete core day.

## Daily signals

`DailySignal` is one human-readable record per usable Oura day. Its fields are
grouped as follows:

| Group | Examples |
| --- | --- |
| Identity and coverage | `day`, `status`, `core_coverage`, `provisional` |
| Sleep | score, hours, display, efficiency, bedtime, wake time |
| Recovery | readiness, HRV, lowest sleeping HR, temperature deviation |
| Activity | activity score, steps, context-only active calories |
| Stress and oxygen | stress/recovery hours, balance, summary, SpO2, BDI |
| Events | workout/session counts, minutes, types, context-only workout calories |
| Baselines | prior median, delta, observation count, baseline status |
| Audit | contributor attention, warnings, sync time, contract versions |

Primary sleep selection is deterministic: prefer `long_sleep`, then the longest
contributing sleep, then the latest end time, then stable source ID. Naps remain
separate and are not silently merged into primary sleep.

## Weekly trends

Weekly rows use calendar weeks and report only observed data. They include:

- expected, usable, complete, partial, provisional, no-data, and error counts;
- sleep, readiness, HRV, and lowest-HR summaries with observation counts;
- prior-baseline deltas;
- steps averages;
- observed stress/recovery totals with coverage days;
- workout counts, minutes, and types;
- contributor frequencies, warnings, and contract versions.

The API never extrapolates missing days.

## Prior-only baselines

Daily baselines use valid observations from the preceding 28 calendar days.
The target day, provisional observations, future data, interpolation, and
forward filling are excluded.

| Status | Observations |
| --- | --- |
| `Sufficient` | 14 or more |
| `Developing` | 7–13 |
| `Unavailable` | fewer than 7; deltas are null |

The features are deterministic comparisons, not health conclusions.

## Interpretation boundaries

Oura data is supporting evidence. The API does not automatically eat back
active calories, set nutrition targets, diagnose conditions, or override
subjective pain, soreness, illness, energy, or performance feedback.
