
import pytest

from backend.services.semantic_search_service import SemanticSearchService


class FakeModel:
    def encode(self, question, normalize_embeddings=True):
        assert question == "retard de livraison"
        assert normalize_embeddings is True
        return [0.1] * 384


class FakeRow:
    def __init__(self):
        self.review_id = "review_001"
        self.order_id = "order_001"
        self.review_text = "A entrega chegou com muito atraso."
        self.similarity = 0.82


class FakeResult:
    def fetchall(self):
        return [FakeRow()]


class FakeConnection:
    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        return False

    def execute(self, sql, params):
        assert params["top_k"] == 3
        assert len(params["embedding"]) == 384
        return FakeResult()


class FakeEngine:
    def connect(self):
        return FakeConnection()


def test_search_returns_expected_results():
    service = SemanticSearchService(
        engine=FakeEngine(),
        model=FakeModel()
    )

    results = service.search("retard de livraison", top_k=3)

    assert len(results) == 1
    assert results[0]["review_id"] == "review_001"
    assert results[0]["order_id"] == "order_001"
    assert results[0]["review_text"] == "A entrega chegou com muito atraso."
    assert results[0]["similarity"] == pytest.approx(0.82)


def test_search_rejects_empty_question():
    service = SemanticSearchService(
        engine=FakeEngine(),
        model=FakeModel()
    )

    with pytest.raises(ValueError, match="question"):
        service.search("   ")


@pytest.mark.parametrize("invalid_top_k", [0, -1, 1.5, True, "5"])
def test_search_rejects_invalid_top_k(invalid_top_k):
    service = SemanticSearchService(
        engine=FakeEngine(),
        model=FakeModel()
    )

    with pytest.raises(ValueError, match="top_k"):
        service.search("retard de livraison", top_k=invalid_top_k)
