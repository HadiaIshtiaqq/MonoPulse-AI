# Third-party notices

MonoPlus's humanizer ([backend/app/agents/humanizer.py](../backend/app/agents/humanizer.py)) adapts ideas and word lists from two MIT-licensed projects. No code is copied verbatim; the pattern catalogue, prompt rules and vocabulary tables are re-implemented in Python.

| Project | What we use | License |
|---|---|---|
| [blader/humanizer](https://github.com/blader/humanizer) by Siqi Chen | The pattern catalogue from `SKILL.md` (based on Wikipedia's "Signs of AI writing"): pattern detection, scoring weights, the rule pass and the Nemotron rewrite prompt | MIT, see [LICENSE-blader-humanizer](LICENSE-blader-humanizer) |
| [lynote-ai/humanize-text](https://github.com/lynote-ai/humanize-text) by Lynote.ai | The translation-chain method (high-temperature LLM rewrite through Chinese and Japanese, then back) used by "Deep" mode, run on Nemotron instead of DeepSeek and Google/Niutrans; part of the AI-vocabulary replacement table | MIT, see [LICENSE-lynote-humanize-text](LICENSE-lynote-humanize-text) |

Like both upstream projects, MonoPlus does not promise that text will pass any particular AI detector. The humanizer exists to make a business's own captions sound like the business, not to misrepresent authorship.
