# MATACS-TH-2026-02: AI Proposal Triage Design

- **Full name:** Azaz Ur Rehman
- **Reference:** MATACS-TH-2026-02
- **Role:** Associate Software Developer
- **Time actually spent:** about 3 hours (design and write-up ≈ 1.5 h, prototype and testing ≈ 1.5 h)

## Files

| File | What it is |
|---|---|
| [`diagram/flow.png`](diagram/flow.png) | Process flow from upload to ranked output, with AI steps, rule steps and human checkpoints |
| [`WRITEUP.md`](WRITEUP.md) | Answers to the five questions |
| [`PROMPTS.md`](PROMPTS.md) | The extraction prompt (and an optional wording prompt), as I would send them |
| [`ranking.json`](ranking.json) | Expected ranking of proposals A–E |
| [`prototype/`](prototype/) | Optional script: extraction with Claude plus rule-based scoring |

## Design in short

AI reads and extracts facts (with quotes). Code does the pass/fail checks, scoring, ranking and flagging. A person reviews flagged items and makes the final decision. Criteria are admin-defined and versioned, so changing them only re-scores stored extractions.

## Result on the sample set

A ranked 1st, E ranked 2nd, D and C flagged for human review, B ineligible. Reasons are in `ranking.json`.

## Assumptions

- Proposals are text-based PDFs; scanned files would need OCR first.
- "Last 5 years" is counted from the date of upload.
- Price is scored against the lowest compliant bid.
- The scoring scales (for example full marks at 12 qualifying installs, or at 8 weeks) are my own choices. In a real tool the admin would set them.
- I did not email questions; I stated my assumptions instead.

## How I used AI tools

I used Claude to help draft the design, write-up, prompt and prototype script, and I ran and tested the prototype myself. When I ran the live extraction, it flagged A and E for a possible experience-window issue that the hand-written test data had missed. I checked the quotes in the audit file and decided to keep it as a reviewer note rather than a hold, because it does not change the ranking. I also hit a crash when no sample files were present and a temperature setting my SDK version did not accept, and fixed both.

## Running the prototype (optional)

```bash
cd prototype
pip install -r requirements.txt
python ranker.py --offline        # scores from stored extracted fields; no API key needed
```

To run the live extraction, copy `.env.example` to `.env`, add your key, and place your own local text files as `prototype/samples/A.txt` … `E.txt`. They are git-ignored on purpose, because the brief says not to publish the proposal text.

```bash
python ranker.py --live
```