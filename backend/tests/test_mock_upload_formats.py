from pathlib import Path

from app.ingest import read_tables


SAMPLE_DATA = Path(__file__).resolve().parents[2] / "sample_data"
MOCK_FORMATS = {
    "mock_claims.json": 2,
    "mock_claims.xml": 1,
    "mock_claims.xlsx": 2,
    "mock_claims.pdf": 1,
    "mock_claims_bundle.zip": 2,
}


def test_mock_upload_formats_are_readable():
    for filename, expected_tables in MOCK_FORMATS.items():
        tables, failed = read_tables([(filename, (SAMPLE_DATA / filename).read_bytes())])

        assert not failed, f"{filename}: {failed}"
        assert len(tables) == expected_tables, filename
        assert all(len(table.df) == 3 for table in tables), filename
