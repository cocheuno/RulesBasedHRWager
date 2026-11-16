# Glossary

Every abbreviation the Desk and the reports may show about a horse, and the words it stands for. The first
time one appears on a screen it is written out with the abbreviation in brackets; a horse-facing string that uses one
without its expansion fails `tests/test_plain.py`. Rule ids (S1, P3, X2 ...) are references, kept in brackets at the end of a note.

| Abbreviation | Means |
|---|---|
| AE | also-eligible |
| AWD | average winning distance |
| BE | break-even |
| CR | class rating |
| DNF | did not finish |
| DPI | dam production index |
| DQ | disqualified |
| E1 | early pace |
| E2 | second-call pace |
| EV | expected value |
| FTS | first-time starter |
| ITM | in the money |
| L60 | last 60 days |
| LP | late pace |
| ML | morning line |
| MTO | main-track-only |
| PP | Prime Power |
| RH | relative humidity |
| ROI | return on investment |
| SPI | sire production index |
| SR | speed rating |
| TF | Timeform |
| YTD | year to date |

## Shorthand the engine used to print, and what it says now

| Was | Now |
|---|---|
| `\bavg\b` | average |
| `\bvs\.?\b` | against |
| `\bpts\b` | points |
| `\bjky/trn\b` | jockey and trainer |
| `\bjky\b` | jockey |
| `\btrn\b` | trainer |
| `\bfigs\b` | speed figures |
| `\bfig\b` | speed figure |
| `\bwks\b` | works |
| `\bwk\b` | work |
| `\bmdn\b` | maiden |
| `\bclm\b` | claiming |
| `\balw\b` | allowance |
| `\bsprint→route\b` | sprint to route |
| `\broute→sprint\b` | route to sprint |
| `(\d(?:\.\d+)?)L\b` | \1 lengths |
| `\b(\d+)yo\b` | \1-year-old |
| `\bhigh-pts\b` | high speed points |
| `\blast-3\b` | last three |
| `\bbest-of-last-3\b` | best of the last three |
| `\bpar-(\d+)\b` | par minus \1 |
| `\bpar\+(\d+)\b` | par plus \1 |
| `\b1st\b` | first |
| `\b2nd\b` | second |
| `\b3rd\b` | third |
| `\bE types\b` | early types |
| `\bE/P\b` | early-presser |
| `\bno\.\s` | number  |

## Race-class codes, printed as Brisnet prints them (they name the race, not the horse)

| Code | Means |
|---|---|
| ALW | allowance |
| CLM | claiming |
| MCL | maiden claiming |
| MSW | maiden special weight |
| OC | optional claiming |
| STK | stakes |

Chart comments in quotes ('4w turn, weakened') are the chart caller's words and are shown as printed.
