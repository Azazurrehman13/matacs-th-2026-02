# Write-up: AI proposal triage design

Flow in one line: upload → read text → **AI extracts facts** → code checks the extracted facts → code applies the mandatory rules → code scores → code ranks and flags → **human reviews and decides**. See `diagram/flow.png`.

**Assumptions:** proposals are text-based PDFs (scans would need an OCR step first). "Last 5 years" is counted from the date of upload. Proposals are referred to by letter only.

## 1. AI vs. rules

**AI does one job: reading messy proposal text and turning it into structured fields** (licence held, price, weeks, warranty years, team items). Proposals are written in free text, and that is where AI is better than code.

**Everything else is plain code:** pass/fail checks, the 0-100 scoring formulas, the weights, ranking, and flags. These must be exact, repeatable and explainable, and the admin must be able to change them without touching a prompt. I put the line where a wrong answer becomes expensive: AI reads, code decides. An optional second AI step may only rephrase the one-line reason from numbers the code already produced.

## 2. Consistency and explainability

- The AI only extracts, and it runs at temperature 0 with a fixed prompt and a fixed output schema. Scoring is code, so the same extracted facts always give the same score.
- **Would two runs match?** The scores will, as long as the extraction matches. Extraction can differ slightly between runs, so I store the first extraction and re-score from that. Re-running extraction is a deliberate, logged action. For the five samples, any difference would show up as a changed field, not a vague change in score.
- Every extracted value comes with a quote from the proposal. Code checks that the quote really appears in the document. If it does not, the value is treated as unknown and flagged.
- The reviewer sees, for each proposal: the extracted fields with their quotes, a per-criterion sub-score, the weight, the weighted points, and any flags. The ranking reason is built from those numbers, so "why is it 2nd?" always has a concrete answer.

## 3. Human in the loop

A person checks at three points:
1. **Extraction review (optional but recommended):** the reviewer can correct any extracted field next to its quote. Corrections re-run the scoring only.
2. **Flag review:** every flagged or unclear proposal is held until a person resolves it (confirms, corrects, or excludes). Nothing flagged is silently ranked or silently dropped.
3. **Final decision:** the tool produces a ranked list only. A human makes the award decision and can override any rank with a written reason.

**Audit log, for every run:** who uploaded, file hashes, criteria version and weights, prompt version, model name and settings, raw extraction, every human edit (who, when, old value, new value, reason), the final ranking, and the final award decision.

## 4. Changing criteria

Criteria are versioned. An edit never changes an old result in place.
- Each score stores the criteria version it was computed with.
- Because extractions are stored, a criteria or weight change can be applied by re-scoring only. No new AI calls are needed and no cost is incurred, unless a new criterion needs a new field extracted.
- The reviewer sees old and new rankings side by side and decides which to use. Awarded or closed categories stay locked to the version used.
- If an admin saves weights that do not total 100%, the tool refuses to save.

## 5. Risks and safeguards

| Risk | Safeguard |
|---|---|
| **Wrong extraction** (e.g. misreading a number) | Quote required for each field and checked by code; reviewer sees quotes; null instead of guessing |
| **Made-up facts** | "Use null if not stated" rule; unsupported values are rejected by the quote check |
| **Manipulation / prompt injection** (C contains an instruction to rank it first) | Proposal text is declared as data in the prompt; the model cannot rank or score; a keyword scan in code is a second check; C is flagged and scored on content only |
| **Vague promises counted as compliance** (B's subcontractor "to be confirmed"; D's schedule "after site assessment") | Mandatory rules need the bidder to hold the licence now; missing values stay null; B is ineligible and D is flagged |
| **Overstated experience** (C says "since 2020", which may go beyond 5 years) | Extractor marks the window as ambiguous; reviewer confirms the count |
| **Bias** (e.g. favouring well-written proposals or big companies) | The model never scores; scoring uses only the admin's criteria; names and company details are not used in scoring; reviewers can compare against raw quotes |
| **Cost** | One extraction call per proposal; stored and reused; scoring and re-scoring are free |
| **Privacy** | Only the proposal text is sent; no keys or personal data in the repo; logs are access-controlled |
| **Price scored relative to the other bids** | Price is scored against the lowest compliant bid, so adding a new proposal can shift other price scores. This is logged and shown to the reviewer. |

## How the sample set ranks

**A (89.3)** first and **E (77.9)** second are fully compliant. **D (72.5)** and **C (69.9)** are held for human review (missing timeline; reviewer-directed instruction). **B** is ineligible despite the lowest price. If a reviewer clears D or C, the code slots them into the ranking by their score.
