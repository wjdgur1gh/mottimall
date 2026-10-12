import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))


@pytest.fixture(scope="session")
def sample_dir(tmp_path_factory):
    """합성 샘플 데이터를 임시 디렉터리에 생성."""
    import make_sample_data as m
    out = tmp_path_factory.mktemp("sample")
    sys.argv = ["make_sample_data.py", "--out", str(out)]
    m.main()
    return out


@pytest.fixture
def cfg():
    from pullback_trader.config import AppConfig, validate
    c = AppConfig()
    validate(c)
    return c
