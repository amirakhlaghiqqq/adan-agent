import importlib.util
from pathlib import Path
from unittest.mock import Mock

import pytest

spec = importlib.util.spec_from_file_location(
    "ingest", Path(__file__).resolve().parents[2] / "scripts" / "ingest.py"
)
ingest = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ingest)


@pytest.mark.parametrize("clean", [True, False])
def test_startup_reuses_index_audits_it_and_closes_connections(monkeypatch, clean):
    config = Mock(is_local_qdrant=False)
    pipeline = Mock()
    pipeline.audit_collection.return_value = Mock(
        is_clean=clean, total_chunks=42, failed_count=0 if clean else 1
    )
    monkeypatch.setattr(ingest, "load_config", lambda: config)
    monkeypatch.setattr(ingest, "RAGPipeline", lambda _: pipeline)
    monkeypatch.setattr("sys.argv", ["ingest.py", "--ensure"])

    if clean:
        ingest.main()
    else:
        with pytest.raises(SystemExit) as error:
            ingest.main()
        assert error.value.code == 1

    pipeline.get_index.assert_called_once_with()
    pipeline.ingest_directory.assert_not_called()
    pipeline.ingest_files.assert_not_called()
    pipeline.audit_collection.assert_called_once_with()
    pipeline.close.assert_called_once_with()
