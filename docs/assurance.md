# Assurance: one fresh course, start to finish

This is the check that a professor can start a **new** course and carry it through the product. The course in the run is **AAS 910, Applied AI systems**. It is not the seeded MAAI 903 sample.

The automated run is the Playwright test `e2e-journey` in `frontend/e2e/journey.spec.ts`. GitHub Actions runs it on every pull request in the `e2e-journey` job of `.github/workflows/ci.yml`.

## What the run does

1. Sign in as `professor@demo.uowd.ac.ae` and land on Home, with the chat bar.
2. Start a blank subject outline, type the name and code, attach a text file, and use **Write a suggestion** for the lecture, description, outcomes, weekly schedule, readings, assessments, and policies.
3. Send the outline for council review. The screen shows a score and how many high findings are still open.
4. Generate the outline. PDF and DOCX links appear, and the status becomes published.
5. Open the group project. Ask for ideas, write exemplars, form four groups of two, and publish the assignment.
6. Sync student submissions. Four groups come back, two as PDF and two as Word.
7. Open integrity for this course, assignment A3, Group A against Group B, and show the two documents side by side.
8. On grading, change one rubric band (the screen says **Changed by you** and the total moves), add a margin comment, approve, and send the grade.
9. The screen says **Sent to Moodle** and **This assignment is complete**. It also says Moodle was not contacted.
10. Open Students at risk for AAS 910.

Screenshots from the local run, 1440 pixels wide:

- `journey-01.png` Home and the chat bar
- `journey-02.png` Outline generated
- `journey-03.png` Council review score
- `journey-04.png` Assignment published, with ideas, groups, and the rubric
- `journey-05.png` Four synced submissions, PDF and DOCX
- `journey-06.png` Integrity, Group A and Group B, documents open
- `journey-07.png` Grade with one band changed
- `journey-08.png` Sent to Moodle, assignment complete
- `journey-09.png` Students at risk for AAS 910

## Tests

| Check | Count | Result here |
| --- | --- | --- |
| Professor unit tests (`backend/tests/test_profassist.py`) | 48 | 48 passed |
| Playwright journey (`e2e-journey`) | 1 | 1 passed locally |
| Other backend test modules | 26 files, 393 collected | Not part of this workflow |

The professor unit tests do not open a database. They check scrubbing, the fake Moodle connector, the integrity board, and the grading draft. The journey test is the one that signs in, writes rows, and clicks through the screens.

The repository coverage gate does **not** measure `app/profassist`. `backend/pyproject.toml` omits that package. There is no coverage percentage for the professor features in CI.

## What is real, and what is faked

Real in this run:

- The professor signs in and the outline, assignment, groups, and submissions are stored in Postgres.
- PDF and DOCX files are built on this machine and opened in the viewer.
- Council review, ideas, and exemplars come from the configured model and are saved.
- The grade push goes through the same Moodle door as a live push.

Faked or synthetic, on purpose:

- **Moodle is in fake mode.** `MOODLE_MODE=fake`. Sync and push are recorded here. Nothing is sent to a university Moodle. The screen says so.
- **The class list is synthetic.** Eight names (Sara Al Maktoum, Omar Haddad, and the others) are demo students, not a real roster.
- **The drafter needs a model.** There is no built-in fallback: without a model key, suggestions, ideas, exemplars, and grade bands stop with an explicit error.
- **At-risk scores are synthetic.** The page is labelled "Synthetic, demo only". It does not change a mark.
- **Home charts** that say "Synthetic term, demo only" are illustrations, not this course's grades.
- **Integrity sentences** for the new assignment are a fixed pair of shared lines so the document view has something real to highlight. They are not a plagiarism engine.

A live model key, or `MOODLE_MODE=real` with the university URL and token, is a different setup. This run does not claim either of those.
