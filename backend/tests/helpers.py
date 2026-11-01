import io
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app import pipeline as PL  # noqa
from app import sample as SM  # noqa


def load_sample(rules=True):
    bundle, truth = SM.build()
    files = [(f"{k}.csv", df.to_csv(index=False).encode()) for k, df in bundle.items()]
    rf = [("judge_rules.txt", SM.JUDGE_RULES.encode())] if rules else []
    S = PL.create_session(files, rf, "")
    PL.run_session(S)
    return S, truth


def by(S, **kw):
    return [f for f in S["findings"] if all(f.get(k) == v for k, v in kw.items())]
