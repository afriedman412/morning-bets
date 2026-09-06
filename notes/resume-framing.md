A few directions, ordered by effort vs. payoff for resume purposes:
Low effort, high payoff

Write a README that frames it like a real project — problem, architecture, stack, results. Even if the code is what it is, the README is what people read first.
Add a "results" section showing the evaluation data: which cappers perform best, what your hit rate is over time, anything quantitative. Turns it from "I built a thing" into "I built a thing and it produces measurable outputs."
Make sure the repo is clean and public (license, requirements, basic setup instructions).

Medium effort

Write a blog post or post on dnpdata.com explaining what the system does and why you built it. Shows you can communicate technical work, which is half the battle for senior roles.
Add a small evaluation/observability layer: log model decisions, track failure modes, show that you've thought about reliability. Even basic logging and dashboard turns a hobby project into a production-shaped one.
If you're not already, treat the scraping → grading → display flow as an explicit pipeline with named stages. Helps the architecture story.

Higher effort

Add an agentic layer that's intentional rather than incidental — for example, an LLM that looks at the historical data and flags cappers who are likely to keep performing or who are slipping. That gives you a "I added an agentic optimization layer to my own production system" story.
Backtesting / replay: prove that the system works against historical data, not just live. That's a real engineering signal.
Reliability patterns: retry logic for failed scrapes, drift detection on capper performance, alerting when something breaks. Same patterns you used in the FEC pipeline, applied to a fun problem.

The framing angle
The story to tell about this project isn't "I built a betting tool." It's "I built a small production agent system that ingests semi-structured data from heterogeneous sources, normalizes it, evaluates against ground truth, and surfaces insights." Reframe the resume description and what you say in interviews accordingly. Same underlying work, very different impression.
Don't overinvest. A clean README and a results section gets you 80% of the resume benefit for a few hours of work.