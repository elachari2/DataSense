from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pandas as pd
import pytest
from streamlit.testing.v1 import AppTest

from backend.database.query_executor import QueryResult
from backend.services.nl2sql_service import NL2SQLResponse


APP_PATH = Path(__file__).resolve().parents[1] / "app.py"


def _sql_response(data=None, success=True, status="success"):
    result = QueryResult(
        sql="SELECT category, total FROM report LIMIT 100",
        success=success,
        data=data,
        row_count=0 if data is None else len(data),
        column_names=[] if data is None else list(data.columns),
        execution_time_seconds=0.02,
        error_message=None if success else "database detail",
    )
    return NL2SQLResponse(
        question="Montre-moi les résultats.",
        status=status,
        sql="SELECT category, total FROM report LIMIT 100",
        is_valid_sql=True,
        execution_result=result,
        total_duration_seconds=0.12,
    )


def _load_app(monkeypatch, response=None, error=None):
    service = MagicMock()
    if error is not None:
        service.process_question.side_effect = error
    else:
        service.process_question.return_value = response

    monkeypatch.setattr(
        "backend.services.question_orchestrator.get_question_orchestrator",
        lambda: service,
    )
    monkeypatch.setattr("src.db.test_connection", lambda: ("PostgreSQL", True))
    monkeypatch.setattr(
        "backend.config.settings.get_settings",
        lambda: SimpleNamespace(llm=SimpleNamespace(model="test-model")),
    )
    readiness = SimpleNamespace(
        table_exists=True,
        has_embeddings=True,
        embedding_dimension=384,
    )
    semantic_service = MagicMock()
    semantic_service.readiness.return_value = readiness
    monkeypatch.setattr(
        "backend.services.semantic_search_service.get_semantic_search_service",
        lambda: semantic_service,
    )
    app = AppTest.from_file(str(APP_PATH)).run()
    return app, service


def test_app_loads_chat_input_and_examples_without_external_services(monkeypatch):
    app, service = _load_app(monkeypatch)

    assert not app.exception
    assert len(app.chat_input) == 1
    assert any("Exemples de questions" in item.value for item in app.info)
    service.process_question.assert_not_called()


def test_gemini_health_check_displays_the_model_that_succeeded(monkeypatch):
    llm_service = MagicMock()
    llm_service.test_connectivity.return_value = {
        "success": True,
        "model": "gemini-fallback",
    }
    monkeypatch.setattr(
        "backend.services.llm_service.get_llm_service",
        lambda: llm_service,
    )
    app, _ = _load_app(monkeypatch)

    next(
        button for button in app.button if button.label == "Tester Gemini"
    ).click().run()

    assert any("via gemini-fallback" in item.value for item in app.success)


def test_quick_example_submits_once_to_the_backend(monkeypatch):
    response = NL2SQLResponse(
        question="Combien de commandes ont été livrées en 2018 ?",
        status="success",
        intent="sql",
        explanation="Résultat calculé.",
    )
    app, service = _load_app(monkeypatch, response=response)

    app.button(key="example_0").click().run()

    service.process_question.assert_called_once_with(
        "Combien de commandes ont été livrées en 2018 ?",
        execute=True,
    )


def test_sql_question_renders_data_and_rerun_does_not_repeat_backend_call(
    monkeypatch,
):
    data = pd.DataFrame(
        {"category": ["A", "B"], "total": [3, 5]}
    )
    app, service = _load_app(monkeypatch, response=_sql_response(data))

    app.chat_input[0].set_value("Quels sont les totaux ?").run()

    service.process_question.assert_called_once_with(
        "Quels sont les totaux ?", execute=True
    )
    assert any("Quels sont les totaux ?" in item.value for item in app.markdown)
    assert len(app.dataframe) == 1

    app.run()

    service.process_question.assert_called_once()


def test_user_can_enable_a_relevant_bar_chart(monkeypatch):
    data = pd.DataFrame({"category": ["A", "B"], "total": [3, 5]})
    app, _ = _load_app(monkeypatch, response=_sql_response(data))

    app.chat_input[0].set_value("Compare les totaux.").run()
    app.selectbox(key="chart_type_1").set_value("Barres").run()

    assert len(app.get("vega_lite_chart")) == 1


def test_chart_is_not_suggested_for_high_cardinality_categories(monkeypatch):
    data = pd.DataFrame(
        {"order_id": [f"order-{index}" for index in range(31)], "total": range(31)}
    )
    app, _ = _load_app(monkeypatch, response=_sql_response(data))

    app.chat_input[0].set_value("Compare les commandes.").run()

    assert len(app.selectbox) == 0


def test_semantic_question_renders_answer_and_review_evidence(monkeypatch):
    response = NL2SQLResponse(
        question="Que disent les avis ?",
        status="success",
        intent="semantic",
        answer="Les clients mentionnent des retards.",
        semantic_results=[
            {
                "review_id": "review-1",
                "order_id": "order-1",
                "review_text": "Livraison arrivée en retard.",
                "similarity": 0.84,
            }
        ],
    )
    app, service = _load_app(monkeypatch, response=response)

    app.chat_input[0].set_value("Que disent les avis ?").run()

    service.process_question.assert_called_once()
    assert any("Les clients mentionnent des retards." in item.value for item in app.markdown)
    assert any(item.label == "Commentaires clients retrouvés" for item in app.expander)
    assert any("Livraison arrivée en retard." in item.value for item in app.text)


def test_mixed_question_renders_sql_table_and_semantic_evidence(monkeypatch):
    sql_response = _sql_response(pd.DataFrame({"category": ["A"], "total": [3]}))
    sql_response.intent = "mixed"
    sql_response.answer = "Les avis associés évoquent la livraison."
    sql_response.semantic_results = [
        {
            "review_id": "review-1",
            "order_id": "order-1",
            "review_text": "Livraison rapide.",
            "similarity": 0.92,
        }
    ]
    app, service = _load_app(monkeypatch, response=sql_response)

    app.chat_input[0].set_value("Quel produit et que disent les avis ?").run()

    service.process_question.assert_called_once()
    assert len(app.dataframe) == 1
    assert any(
        "Les avis associés évoquent la livraison." in item.value
        for item in app.markdown
    )
    assert any("Livraison rapide." in item.value for item in app.text)


def test_new_conversation_clears_session_history(monkeypatch):
    response = NL2SQLResponse(
        question="Total ?",
        status="success",
        intent="sql",
        explanation="Résultat calculé.",
    )
    app, service = _load_app(monkeypatch, response=response)
    app.chat_input[0].set_value("Total ?").run()
    assert len(app.session_state["conversation"]) == 2
    service.process_question.assert_called_once()

    app.button(key="new_conversation").click().run()

    assert app.session_state["conversation"] == []
    service.process_question.assert_called_once()


def test_backend_exception_is_shown_without_internal_details(monkeypatch):
    app, service = _load_app(
        monkeypatch,
        error=RuntimeError("secret connection detail"),
    )

    app.chat_input[0].set_value("Question indisponible").run()

    service.process_question.assert_called_once()
    assert any("temporairement indisponible" in item.value for item in app.error)
    assert all("secret connection detail" not in item.value for item in app.error)


def test_empty_sql_results_show_an_informative_message(monkeypatch):
    response = _sql_response(pd.DataFrame(), success=True)
    app, _ = _load_app(monkeypatch, response=response)

    app.chat_input[0].set_value("Résultats vides ?").run()

    assert any("aucun enregistrement" in item.value for item in app.info)


def test_sql_execution_error_does_not_expose_database_error(monkeypatch):
    response = _sql_response(success=False, status="execution_error")
    app, _ = _load_app(monkeypatch, response=response)

    app.chat_input[0].set_value("Échec SQL ?").run()

    assert any("Les résultats SQL ne sont pas disponibles." in item.value for item in app.warning)
    assert all("database detail" not in item.value for item in app.warning)


def test_gemini_failure_is_presented_without_provider_details(monkeypatch):
    response = NL2SQLResponse(
        question="Question",
        status="error",
        intent="semantic",
        error_code="GEMINI_PROVIDER_UNAVAILABLE",
        provider_status=503,
        error_message="private API response",
    )
    app, _ = _load_app(monkeypatch, response=response)

    app.chat_input[0].set_value("Question").run()

    assert any("HTTP 503" in item.value for item in app.error)
    assert all("private API response" not in item.value for item in app.error)


def test_semantic_search_failure_has_actionable_safe_message(monkeypatch):
    response = NL2SQLResponse(
        question="Que disent les avis ?",
        status="error",
        intent="semantic",
        error_code="SEMANTIC_TABLE_MISSING",
        error_message="private relation detail",
    )
    app, _ = _load_app(monkeypatch, response=response)

    app.chat_input[0].set_value("Que disent les avis ?").run()

    assert any("public.reviews_semantic" in item.value for item in app.error)
    assert all("private relation detail" not in item.value for item in app.error)


@pytest.mark.parametrize(
    ("status", "message"),
    [
        ("clarification_required", "Merci de préciser votre question."),
        ("security_rejected", "contrôle de sécurité SQL"),
        ("unsupported", "Cette question ne peut pas être traitée."),
        ("error", "Le traitement a échoué."),
    ],
)
def test_backend_statuses_have_user_facing_messages(monkeypatch, status, message):
    response = NL2SQLResponse(
        question="Question",
        status=status,
        explanation="",
        error_message="secret detail",
        error_code="UNKNOWN",
    )
    app, _ = _load_app(monkeypatch, response=response)

    app.chat_input[0].set_value("Question").run()

    displayed = [
        item.value
        for collection in (app.warning, app.error, app.info)
        for item in collection
    ]
    assert any(message in value for value in displayed)
    assert all("secret detail" not in value for value in displayed)
