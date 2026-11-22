import pytest

from credito.corpus.fetch import FetchError
from credito.corpus.sources import Source
from scripts.download_corpus import download_source

PLANALTO = Source(id="lei1", label="Lei 1", title="t", kind="planalto", url="https://planalto/l1.htm")


def test_artigo_repetido_derruba_o_download(tmp_path):
    html = "<p>Art. 1º Texto antigo.</p><p>Art. 1º Texto novo.</p><p>Art. 2º Outro.</p>"
    with pytest.raises(FetchError, match="1º"):
        download_source(PLANALTO, tmp_path, get=lambda url: html.encode("cp1252"))
    assert not (tmp_path / "lei1.txt").exists()
