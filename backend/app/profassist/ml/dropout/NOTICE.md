# Student course-withdrawal model

The `upstream/` directory in this folder is a substantial port of the public
repository [maxser0v/student-dropout-mlops](https://github.com/maxser0v/student-dropout-mlops)
(commit history on `main` as of 2026-11-22). That repository ships **no LICENSE
file**. Upstream therefore grants no redistribution or production-use rights.

What was ported: the validation, training, feature, score, registry, monitor,
model_io, lineage, and gates modules, plus upstream documentation such as
`UPSTREAM_README.md` and `LMS_EXPORT_SPEC.md`. This is not merely a set of
feature names or a pipeline shape.

This port is included for contract/demo purposes only. Redistribution or
production use requires written permission from the upstream author. Do not
claim that it is "contract-only" or that a license was granted: the upstream
project has no LICENSE file, and this repository does not claim one.

The upstream training CSVs are not in the git tree. `artifacts/model.joblib` is a
logistic regression fit on synthetic Moodle-shaped rows by `train_synthetic.py`.
It is labelled demo only. It is not trained on real students, and
`automatic_actions` stays false.

The upstream model, when trained on its synthetic bundle, is a scikit-learn
pipeline: median imputation, missingness indicators, standard scaling, and
logistic regression with seed 903. Its threshold in the published model card is
0.15. It predicts course withdrawal after day 35, not leaving the university.
There is no SHAP step in the upstream scorer. Feature contributions would come
from the logistic-regression coefficients after a model is registered.
