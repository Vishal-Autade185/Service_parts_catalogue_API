# Notes

## Decisions

**1. Stayed with FastAPI**
FastAPI runs on Uvicorn, which is an async server. It has built-in validation through Pydantic and
gives API docs automatically at `/docs`.

**2. Rule-based system, not ML**
Grading is based on an exact match, so I went with clear rules. An ML model would only add
uncertainty and complexity, and it isn't needed for this problem.

**3. Fail-safe logic**
If a BOM row is missing an important value (like a part number or a valid quantity), I skip it
instead of guessing. Shipping the wrong part is worse than leaving a row out.

**4. Service flag conflict**
If a part has both Y and N, I take N. The data is contradicting itself, and marking it not
replaceable is the safe choice: the engineer double-checks instead of shipping a part that might
not fit.

**5. Plain DFS instead of a graph library**
I didn't use a graph library because it adds an extra dependency and gives me less control over
things like which edge to remove in a cycle. The graph is small, so a dictionary with DFS is enough.

**6. Cycles and paths**
I'll be honest, this part was suggested by AI, and I cross-checked it against the expected answers
before using it. DFS finds and removes cycles, Kahn's algorithm puts the parts in order and confirms
no cycle is left, and dynamic programming calculates the total quantities and path counts.

**7. Architecture**
I looked at options like a graph database and graph libraries. The main tradeoff was that they add
external dependencies, which makes running the app in a single command harder, and the system
becomes more complicated and tightly coupled. So I went with in-memory storage. It easily handles
thousands of parts (I tested it with about 1,700 parts and 4,000 BOM rows).

**8. Docker**
I was sure from the start that I would dockerize this. In the past I've had apps that ran on one
machine and not on another, so with Docker it runs the same everywhere.

## What I cut

**1. Database:** the data is small and the CSV files are the source, so there's nothing to lose.
On a cold start the app is live again within seconds.

**2. Cache:** I first planned to add one, but the paths are already precomputed, so it didn't make
sense. It would also need extra setup (like Redis).

**3. Some columns:** I didn't use `category` and `unit_cost` because they don't appear in any API
response.

## Limitations

**1. Large paths:** if a BOM is very deep or has a huge number of paths, it can slow things down.

**2. Data rule ambiguity:** I tried to cover and generalize all the cases I could find, but if some
edge case is missed, that row may get skipped.

## Next steps

**1. Deployment:** deploy it on the cloud with CloudWatch for monitoring.
