# Data

## The three files

- `bom.csv`: which assembly contains which part, and how many (`parent_pn`, `child_pn`, `quantity`).
- `parts_master.csv`: description and revision of each part. A part can have several rows, one per
  revision. `category` and `unit_cost` are not used.
- `service_parts.csv`: whether a part can be replaced on site (`field_replaceable` Y/N) and which
  machine serial numbers it fits (`serial_from`, `serial_to`).

The top-level part is `AS-40000`. Only parts inside it count as "in the machine".

## What I found in the visible data

| Finding | Count |
|---|---|
| Rows in bom / parts_master / service_parts | 1,287 / 950 / 854 |
| BOM part numbers with stray spaces or lower case (e.g. `' AS-40133'`, `'fa-30013 '`) | 20 |
| BOM edges exported more than once (all with the same quantity) | 40 |
| Parts with more than one revision (A, B, C) | 63 |
| Relationship that creates a cycle | 1 (`AS-40209 -> AS-40002`) |
| Parts not inside AS-40000 (orphans) | 5 |
| Parts in the machine but not in parts_master | 25 |
| Service flags | 485 `Y`, 369 `N`; no conflicts, no broken serial ranges |

After cleaning: **875 parts: 483 ready, 25 missing, 367 not_replaceable.**

The visible data is fairly clean. Most of the rules below are there for messier exports, because
the data can be replaced with a different export.

## Rules

| Problem | What I do | Alternative | Why |
|---|---|---|---|
| Same part typed differently (case, spaces, dash look-alikes, full-width or invisible characters) | Clean it: upper case, remove all whitespace and invisible characters, turn every dash into `-` | Match exactly as typed | A part number identifies one part however a system types it |
| Separator variants across files (`AS40003` vs `AS-40003`) | Use the BOM spelling if exactly one BOM part matches when separators are ignored | Always merge, or never merge | Merging when two BOM parts could match would mix up two real parts |
| Quantity `3.0`, `1,000`, ` 3 ` | Read as the whole number | Reject the row | `3.0` only means 3; rejecting it would drop a whole sub-assembly |
| Quantity blank, `abc`, `2.5`, `0` or negative | Skip that row | Guess (e.g. 1) | A guessed quantity means ordering the wrong count |
| Blank part number, or a part containing itself | Skip that row | - | It can't be a real relationship |
| Same BOM edge listed several times | Keep it once | Add the quantities | Exporting a fact twice doesn't change it |
| Same edge with different quantities | Most common quantity; on a tie, the tied value seen first in the file | Largest, or last | Doesn't depend on row order when there is a clear majority |
| Several revisions of a part | Highest revision wins (`""` < A < B < ... < Z < AA); on a tie, the first row | Last row in the file | The brief says to use the latest revision |
| Several separator variants of one part in parts_master, none spelled like the BOM | Merge their rows, then pick the highest revision | Leave them unmatched | Otherwise a real part would show as missing |
| Flag `Yes`, `TRUE`, `1` / `No`, `FALSE`, `0` | Same as Y / N | Only accept `Y`/`N` | They clearly mean the same thing |
| Unknown flag (`TBD`, `?`) | Treat as N | Treat as Y | An unclear value must never make a part `ready` |
| Part marked both Y and N | N wins | Y wins | Contradictory data: the safe answer is "not replaceable" |
| Serial range missing one end (`1000` to blank) | Open-ended range | Fits nothing | Exports use this to mean "from 1000 onwards" |
| Serial range reversed or not a number | Fits no serial (part can still be `ready`) | Fits every serial | Junk must never turn into "fits everything" |
| Part not inside AS-40000 (orphan) | Left out completely, and never counted as a parent | Keep it | Not in the machine means not in the catalogue |
| Missing file or required column | Startup stops with a clear message | Start with no data | Nothing useful can be answered without it |
| Anything else odd in a row | Skip that row and carry on | Stop the service | One bad row must never take the service down |

## Relationship removed

`AS-40209 -> AS-40002` (quantity 1) was left out.

Coming down from the top, `AS-40209` already sits inside `AS-40002`:
`AS-40000 > AS-40001 > AS-40002 > AS-40208 > AS-40209`. So this row says an assembly contains a part
it is already inside. That is the wrong relationship described in the brief: it points back up from
inside the machine.

How the rule works in general: a depth-first search from the top finds the relationship that closes
the loop. If one part in the loop only contains other parts of the loop (for example a fastener that
wrongly "contains" an assembly), the relationship out of that part is removed instead, as long as no
part drops out of the machine. Every removed relationship is also written to the startup log.

## Known ambiguities

- **Two real assemblies listing each other:** if both contain other parts too, nothing in the data
  says which listing is wrong. The rule then removes the one the depth-first search reaches first
  (children visited in part-number order), so the result is always the same.
- **Newline inside a part number in a URL:** it gets a plain "Not Found" 404 instead of the usual
  "not in the machine" message. Real part numbers don't contain newlines.

## How I tested the rules

The grader swaps in a different export, so the tests don't only check the visible answers. They
check that every rule still holds when the data gets messy. There are 404 tests in `tests/`, all
offline (403 run by default, 1 heavy one is opt-in).

| Test file | Tests | What it proves |
|---|---|---|
| `test_loader.py` | 93 | Every cleaning rule on its own: part-number spellings, numbers like `3.0`/`1,000`/`2.5`, Y/N spellings, revision order, file encodings, odd headers, ragged rows, duplicates, conflicts, aliases |
| `test_worked_example.py` | 9 | The worked example from the brief gives exactly its stated answers (4 parts, FA-9 total 10, revision B, its two paths, serial 2500 -> 2) |
| `test_real_data.py` | 9 | The visible data gives the expected answers (875 / 483 / 25 / 367, the removed cycle edge, totals and paths of key parts) |
| `test_catalogue.py` | 19 | Cycles of every shape, including 5 tricky cases where only one edge is the right one to remove; orphans; a 2,000-level-deep BOM |
| `test_cycles_injected.py` | 9 | Take the clean visible BOM, add 1, 3 or 5 random "points back up" edges, 1,000 times for each of 3 random seeds. The rule removes exactly the injected edges 1000/1000 times for 1 and 3 edges, and 999-1000/1000 for 5. Plain depth-first search alone would get about 97%, 92% and 88% |
| `test_invariance.py` | 21 | Corrupt a copy of the visible data in one way (lower case, extra spaces, invisible characters, full-width letters, en dashes, `3.0` quantities, `Yes`/`No` flags, every row twice, shuffled rows, renamed headers, extra columns, other line endings, Windows encoding) and check every answer stays exactly the same. Four corruptions must change the answer in a known way (bad quantity, reversed range, `TBD` flag, Y+N conflict), and the test checks that exact change |
| `test_random_crosscheck.py` | 200 | 200 random small BOMs with cycles, orphans, duplicates and bad rows, compared with a separate brute-force calculation written only for the test |
| `test_safety_nets.py` | 5 | Forces each fallback to run (cycle rule crashing, loop limit reached, a cycle surviving) and checks the service still starts with correct answers |
| `test_api.py` | 35 | Every endpoint: field order, part numbers typed any way, `#` and `/` in part numbers, unknown parts always 404, serial numbers (negative, `+7`, `007`, 1,000 digits) and bad serials always 400 |
| `test_performance.py` | 4 | Speed: every request on the visible data, a 2,000-level chain, a BOM with 65,536 paths to one part, and (opt-in) 1,048,576 paths |

Besides these, I generated a larger messy dataset locally (1,677 parts, about 4,000 BOM rows, every
kind of problem above mixed together, plus 3 hidden cycle edges). Its expected answers were worked
out separately from a clean version of the same machine, not by the app. The app matched all of
them: every part, every path count, every serial check and exactly the 3 cycle edges.
