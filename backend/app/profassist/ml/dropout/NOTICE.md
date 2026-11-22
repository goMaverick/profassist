# Student course-withdrawal model

The feature contract in this folder is ported from the public repository
[maxser0v/student-dropout-mlops](https://github.com/maxser0v/student-dropout-mlops)
(commit history on `main` as of 2026-11-22). That repository does not ship a
LICENSE file. This port keeps the attribution and does not claim a license the
upstream project did not grant. It is a demonstration contract, not a right to
use the model on real students.

What was ported: the 14 allowlisted feature names, the scikit-learn pipeline
shape, and the rule that a score is advisory only. The upstream training CSVs
are not in the git tree. `artifacts/model.joblib` is a logistic regression fit
on synthetic Moodle-shaped rows by `train_synthetic.py`. It is labelled demo
only. It is not trained on real students, and `automatic_actions` stays false.

The upstream model, when trained on its synthetic bundle, is a scikit-learn
pipeline: median imputation, missingness indicators, standard scaling, and
logistic regression with seed 903. Its threshold in the published model card is
0.15. It predicts course withdrawal after day 35, not leaving the university.
There is no SHAP step in the upstream scorer. Feature contributions would come
from the logistic-regression coefficients after a model is registered.
