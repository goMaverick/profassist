# ProfAssist ML integration screenshots

Chrome captured these screens from a local ProfAssist instance using an isolated synthetic workspace.

| Screenshot | What it shows |
| --- | --- |
| [Completed report scan](01-integrity-scan.png) | A live plagiarism scan completed through Prefect and the Linux model worker. |
| [Matched passage](02-integrity-evidence.png) | Integrity displays the persisted worker result for the selected assignment and pair. |
| [Students at risk](03-students-dropout.png) | The roster shows seven saved synthetic predictions and one unscored student. |
| [Dropout exports and jobs](04-dropout-models.png) | Models displays completed training, scoring, and monitoring results replayed from the verified synthetic run. |
| [Reviewed dataset snapshot](05-plagiarism-snapshot.png) | The live freeze action completed and enabled the Train candidate control. |

The browser check used fictional records. The live-data importer rejected the synthetic dropout export. The fixture release shown in Models was seeded for the browser rehearsal. Live Moodle imports and production release approval were outside this check.
