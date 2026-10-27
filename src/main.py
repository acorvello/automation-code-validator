#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Cypress LangGraph Validator - entry point.

Runs the LangGraph pipeline (parser -> evaluator -> (fixer | END)) against
Cypress logs and exposes a small Web UI (Flask) to drive the pipeline and to
manage the Ollama configuration.

Run the Web UI:
    python src/main.py

Run the graph once in the terminal (no Web UI):
    python src/main.py --cli
"""

import os
import sys

# Bootstrap: make sure the project root is importable so that `import src...`
# works regardless of how the script is launched (e.g. `python src/main.py`).
_PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

import argparse
import json
import time
from typing import Dict, Optional

from flask import Flask, jsonify, request
from langchain_core.runnables import RunnableConfig
from pydantic import ValidationError

app = Flask(__name__)
app = Flask(__name__)


from langgraph.graph import END, StateGraph

from src.agents.nodes.parser import parse_logs_node
from src.core.schemas import EvaluatorResponse
from src.core.state import GraphState
from src.utils.config import get_input_path, load_config, save_config
from src.utils.llm_client import CancellationToken, GenerationCancelledError, OllamaClient
from src.utils.prompt_loader import PromptLoader


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _anomaly_fields(anomaly) -> Dict:
    """Normalize an anomaly (Pydantic model or plain dict) into a dict."""
    if hasattr(anomaly, "model_dump"):
        return anomaly.model_dump()
    return dict(anomaly)


def _now() -> str:
    return time.strftime("%H:%M:%S")


FIXABLE_CLASSIFICATIONS = {"ERR_AMBIGUOUS_SELECTOR", "FLAKY_SELECTOR"}


def _normalize_evaluation_response(
    payload,
    anomaly_id: str,
    error_type: Optional[str] = None,
    flakiness_score: Optional[float] = None,
) -> tuple[Dict, bool]:
    fallback = {
        "anomaly_id": anomaly_id,
        "classification": "UNCLASSIFIED",
        "reasoning": "The evaluator response was invalid or incomplete.",
        "needs_fix": False,
        "recommendation": "Review the anomaly manually; no automated fix was approved.",
    }
    response = None
    try:
        if isinstance(payload, dict):
            response = EvaluatorResponse.model_validate(payload, strict=True)
    except ValidationError:
        pass

    parser_policy = {
        "INFRA_FAILURE": (
            "INFRA_FAILURE",
            "The parser identified an infrastructure or network failure.",
            "Check service availability, network connectivity, or credentials.",
        ),
        "AMBIGUOUS_SELECTOR": (
            "ERR_AMBIGUOUS_SELECTOR",
            "The parser found explicit evidence that multiple elements matched.",
            "Use the supplied context to identify a unique locator; do not guess.",
        ),
        "UNKNOWN_TIMEOUT": (
            "UNCLASSIFIED",
            "The timeout does not identify a network failure or a specific element lookup.",
            "Inspect the original failure context before changing the test.",
        ),
    }
    if error_type in {
        "ELEMENT_NOT_FOUND", "ELEMENT_NOT_INTERACTABLE", "ELEMENT_TIMEOUT"
    }:
        if flakiness_score is not None and flakiness_score >= 0.6:
            parser_policy[error_type] = (
                "FLAKY_SELECTOR",
                "The parser identified an element lookup failure with a high flakiness score.",
                "Use the detected framework's stable locator strategy.",
            )
        else:
            parser_policy[error_type] = (
                "LOGIC_OR_STATE_ERROR",
                "The element failure has a low or unavailable flakiness score.",
                "Review application state and test expectations; do not change the locator.",
            )

    if error_type in parser_policy:
        classification, reasoning, recommendation = parser_policy[error_type]
        expected_needs_fix = classification in FIXABLE_CLASSIFICATIONS
        normalized = {
            "anomaly_id": anomaly_id,
            "classification": classification,
            "reasoning": reasoning,
            "needs_fix": expected_needs_fix,
            "recommendation": recommendation,
        }
        consistent = (
            response is not None
            and response.classification == classification
            and response.needs_fix == expected_needs_fix
        )
        return normalized, consistent

    if response is None:
        return fallback, False

    expected_needs_fix = response.classification in FIXABLE_CLASSIFICATIONS
    return {
        "anomaly_id": anomaly_id,
        "classification": response.classification,
        "reasoning": response.reasoning,
        "needs_fix": expected_needs_fix,
        "recommendation": response.recommendation,
    }, response.needs_fix == expected_needs_fix


def _match_installed_model(configured: str, installed: list[str]) -> Optional[str]:
    """Return the installed model name matching the configured one.

    Matching is exact first, then by model family (ignoring the ``:tag``
    suffix) so ``qwen3.5`` matches ``qwen3.5:9b``.
    """
    if configured in installed:
        return configured
    configured_base = configured.split(":")[0]
    for name in installed:
        if name.split(":")[0] == configured_base:
            return name
    return None


def _make_client(cancellation_token: Optional[CancellationToken] = None) -> OllamaClient:
    """Create an Ollama client using the current configuration values.

    Validates the configured model against the Ollama ``/api/tags`` endpoint
    and falls back to the first installed model when the configured one is
    missing. If the server is unreachable the configured model is kept.
    """
    cfg = load_config()
    preferred_model = cfg["ai"].get("preferred_model", "ollama")
    if preferred_model != "ollama":
        raise ValueError(
            f"The selected provider '{preferred_model}' is not integrated. "
            "Only Local LLM (Ollama) is currently supported."
        )

    model = cfg["ollama"]["model"]
    base_url = cfg["ollama"]["host"]
    client_options = {"model": model, "base_url": base_url}
    if cancellation_token is not None:
        client_options["cancellation_token"] = cancellation_token
    client = OllamaClient(**client_options)

    installed = client.list_models()
    matched = _match_installed_model(model, installed) if installed else None
    if matched is None:
        if installed:
            print(
                f"Aviso: modelo '{model}' não encontrado no Ollama "
                f"(instalados: {', '.join(installed)}). Usando '{installed[0]}'."
            )
        else:
            print(f"Aviso: Ollama inacessível em {base_url}. Usando '{model}' configurado.")
        client.model = installed[0] if installed else model
    else:
        client.model = matched
    return client


def check_ollama_ready() -> Dict:
    """Verify Ollama is reachable and resolve the configured model before a run."""
    cfg = load_config()
    preferred_model = cfg["ai"].get("preferred_model", "ollama")
    if preferred_model != "ollama":
        raise ValueError(
            f"The selected provider '{preferred_model}' is not integrated. "
            "Only Local LLM (Ollama) is currently supported."
        )

    base_url = cfg["ollama"]["host"]
    configured_model = cfg["ollama"]["model"]
    client = OllamaClient(model=configured_model, base_url=base_url)
    installed_models = client.list_models()
    if not installed_models:
        raise RuntimeError(
            f"Ollama did not respond or has no installed models at {base_url}."
        )

    model = _match_installed_model(configured_model, installed_models)
    return {
        "host": base_url,
        "model": model or installed_models[0],
        "used_fallback": model is None,
    }


# ---------------------------------------------------------------------------
# Graph nodes
# ---------------------------------------------------------------------------
def evaluator_node(state: GraphState, config: Optional[RunnableConfig] = None) -> Dict:
    """Evaluate every detected anomaly with the LLM and decide if a fix is needed."""
    anomalies = state.get("detected_anomalies") or []
    history = list(state.get("execution_history") or [])
    source_code = state.get("source_code")
    framework = state.get("framework", "Unknown")
    language = state.get("language", "Unknown")
    cancellation_token = (config or {}).get("configurable", {}).get("cancellation_token")
    client = _make_client(cancellation_token=cancellation_token)

    history.append({
        "node": "evaluator",
        "message": f"--- Executando Nó de Avaliação (Ollama: {client.model}) ---",
        "timestamp": _now(),
    })

    evaluations = []
    needs_fix = False  # initialized before use (fix: avoid UnboundLocalError)
    for anomaly in anomalies:
        fields = _anomaly_fields(anomaly)
        prompt = (
            PromptLoader.get_prompt("evaluator", framework, language)
            + "\n\n# ANOMALY TO EVALUATE\n"
            + f"- Anomaly ID: {fields.get('id')}\n"
            + f"- Severity: {fields.get('severity')}\n"
            + f"- Error type: {fields.get('error_type') or 'UNKNOWN'}\n"
            + f"- Error description: {fields.get('description')}\n"
            + f"- Affected locator: {fields.get('selector_affected') or 'N/A'}\n"
            + f"- Flakiness score: {fields.get('flakiness_score')}\n"
            + f"- Framework: {framework}\n"
            + f"- Language: {language}\n"
        )
        if source_code:
            prompt += f"\n# Source code context\n{source_code}\n"

        result, response_consistent = _normalize_evaluation_response(
            client.generate_json_response(prompt),
            fields.get("id", "unknown"),
            error_type=fields.get("error_type"),
            flakiness_score=fields.get("flakiness_score"),
        )
        if not response_consistent:
            history.append({
                "node": "evaluator",
                "message": (
                    f">> WARNING: invalid or inconsistent evaluator response for anomaly "
                    f"{fields.get('id')}; using a fail-closed decision."
                ),
                "timestamp": _now(),
            })
        eval_needs_fix = result["needs_fix"]
        if eval_needs_fix:
            needs_fix = True
        evaluations.append(result)

    metrics = dict(state.get("evaluation_metrics") or {})
    metrics["evaluations"] = evaluations
    metrics["actionable_fix_available"] = any(e["needs_fix"] for e in evaluations)

    history.append({
        "node": "evaluator",
        "message": f">> Resultado da IA: needs_fix={needs_fix} ({len(evaluations)} anomalias avaliadas)",
        "timestamp": _now(),
    })

    return {
        "needs_fix": needs_fix,
        "evaluation_metrics": metrics,
        "execution_history": history,
        "current_node": "evaluator",
    }


def fixer_node(state: GraphState, config: Optional[RunnableConfig] = None) -> Dict:
    """Generate a selector fix for the anomalies flagged as fixable."""
    anomalies = state.get("detected_anomalies") or []
    evaluations = (state.get("evaluation_metrics") or {}).get("evaluations") or []
    evaluations_by_id = {
        evaluation.get("anomaly_id"): evaluation
        for evaluation in evaluations
        if evaluation.get("anomaly_id") is not None
    }
    history = list(state.get("execution_history") or [])  # fix: initialize history
    source_code = state.get("source_code")
    file_path = state.get("current_file_path")
    if not source_code and file_path and os.path.splitext(file_path)[1].lower() != ".txt":
        try:
            with open(file_path, "r", encoding="utf-8") as f:
                source_code = f.read()
        except OSError:
            source_code = None

    cancellation_token = (config or {}).get("configurable", {}).get("cancellation_token")
    client = _make_client(cancellation_token=cancellation_token)
    history.append({
        "node": "fixer",
        "message": f"--- Executando Nó de Correção (Ollama: {client.model}) ---",
        "timestamp": _now(),
    })

    lines = []
    for anomaly in anomalies:
        fields = _anomaly_fields(anomaly)
        evaluation = evaluations_by_id.get(fields.get("id"))
        if (
            not evaluation
            or evaluation.get("needs_fix") is not True
            or evaluation.get("classification") not in FIXABLE_CLASSIFICATIONS
        ):
            continue
        lines.append(
            f"- Anomaly ID: {fields.get('id')}\n"
            f"  Error type: {fields.get('error_type') or 'UNKNOWN'}\n"
            f"  Description: {fields.get('description')}\n"
            f"  Locator: {fields.get('selector_affected') or 'N/A'}\n"
            f"  Classification: {evaluation.get('classification')}\n"
            f"  Reasoning: {evaluation.get('reasoning', '')}\n"
            f"  Recommendation: {evaluation.get('recommendation', '')}"
        )
    if not lines:
        history.append({
            "node": "fixer",
            "message": ">> No validated fixable anomalies; skipping code generation.",
            "timestamp": _now(),
        })
        return {
            "fix_suggestion": "",
            "source_code": source_code,
            "execution_history": history,
            "current_node": "fixer",
        }

    prompt = (
        PromptLoader.get_prompt(
            "fixer", state.get("framework", "Unknown"), state.get("language", "Unknown")
        )
        + "\n\n# ANOMALIES TO FIX\n"
        + "\n".join(lines)
    )
    if source_code:
        prompt += f"\n\n# SOURCE CODE OF THE AFFECTED FILE\n{source_code}"

    fix_suggestion = client.generate_response(prompt).strip()
    if fix_suggestion == "NO_SAFE_FIX":
        fix_suggestion = ""

    history.append({
        "node": "fixer",
        "message": f">> Correção gerada ({len(fix_suggestion)} caracteres)",
        "timestamp": _now(),
    })

    return {
        "fix_suggestion": fix_suggestion,
        "source_code": source_code,
        "execution_history": history,
        "current_node": "fixer",
    }


# ---------------------------------------------------------------------------
# Graph wiring
# ---------------------------------------------------------------------------
def should_continue(state: GraphState) -> str:
    """Route after evaluation: go to the fixer only when a fix is needed."""
    return "fixer" if state.get("needs_fix") else "end"


def build_graph():
    """Build and compile the LangGraph state machine."""
    builder = StateGraph(GraphState)

    builder.add_node("parser", parse_logs_node)
    builder.add_node("evaluator", evaluator_node)
    builder.add_node("fixer", fixer_node)

    builder.set_entry_point("parser")
    builder.add_edge("parser", "evaluator")
    builder.add_conditional_edges("evaluator", should_continue, {
        "fixer": "fixer",
        "end": END,
    })
    builder.add_edge("fixer", END)
    return builder.compile()

GRAPH = build_graph()
def run_validation_graph(raw_logs: str, file_path: Optional[str] = None) -> Dict:
    """
    Runs the validation graph and returns the final state.
    """
    initial_state = _initial_state(raw_logs, file_path=file_path)
    try:
        final_state = GRAPH.invoke(initial_state)
        return {
            "success": True,
            "data": {
                "execution_history": final_state.get("execution_history"),
                "detected_anomalies": final_state.get("detected_anomalies"),
                "evaluation_metrics": final_state.get("evaluation_metrics"),
                "needs_fix": final_state.get("needs_fix"),
                "fix_suggestion": final_state.get("fix_suggestion"),
                "framework": final_state.get("framework", "Unknown"),
                "language": final_state.get("language", "Unknown"),
            }
        }
    except Exception as e:
        return {
            "success": False,

            "error": str(e)
        }


def stream_validation_graph(
    raw_logs: str,
    file_path: Optional[str] = None,
    cancellation_token: Optional[CancellationToken] = None,
):
    """Yield progress events as each validation graph node completes."""
    initial_state = _initial_state(raw_logs, file_path=file_path)
    final_state = None
    initial_update = True

    try:
        stream_config = {
            "configurable": {"cancellation_token": cancellation_token}
        }
        for state in GRAPH.stream(
            initial_state,
            config=stream_config,
            stream_mode="values",
        ):
            if cancellation_token is not None:
                cancellation_token.raise_if_cancelled()
            if initial_update:
                initial_update = False
                continue
            final_state = state
            current_node = state.get("current_node")

            if current_node == "parser":
                anomaly_count = len(state.get("detected_anomalies") or [])
                yield {
                    "type": "progress",
                    "message": f"[PARSER] Found {anomaly_count} anomalie(s).",
                }
                yield {
                    "type": "progress",
                    "message": f"[EVALUATOR] Evaluating {anomaly_count} anomalie(s) with Ollama...",
                }
            elif current_node == "evaluator":
                metrics = state.get("evaluation_metrics") or {}
                evaluations = metrics.get("evaluations") or []
                needs_fix = bool(state.get("needs_fix"))
                yield {
                    "type": "progress",
                    "message": (
                        f"[EVALUATOR] Completed {len(evaluations)} evaluation(s); "
                        f"needs_fix={needs_fix}."
                    ),
                }
                if needs_fix:
                    yield {
                        "type": "progress",
                        "message": "[FIXER] Generating a correction suggestion with Ollama...",
                    }
            elif current_node == "fixer":
                suggestion = state.get("fix_suggestion") or ""
                yield {
                    "type": "progress",
                    "message": f"[FIXER] Suggestion generated ({len(suggestion)} characters).",
                }

        if final_state is None:
            raise RuntimeError("The validation graph returned no state.")

        yield {
            "type": "result",
            "success": True,
            "data": {
                "execution_history": final_state.get("execution_history"),
                "detected_anomalies": [
                    _anomaly_fields(anomaly)
                    for anomaly in final_state.get("detected_anomalies") or []
                ],
                "evaluation_metrics": final_state.get("evaluation_metrics"),
                "needs_fix": final_state.get("needs_fix"),
                "fix_suggestion": final_state.get("fix_suggestion"),
                "framework": final_state.get("framework", "Unknown"),
                "language": final_state.get("language", "Unknown"),
            },
        }
    except GenerationCancelledError:
        yield {"type": "cancelled", "message": "Inspection stopped by user."}
    except Exception as error:
        yield {"type": "result", "success": False, "error": str(error)}

@app.route("/api/run-validation", methods=["POST"])
def api_run_validation():
    data = request.get_json()
    logs = data.get("logs", "")
    file_path = data.get("file_path")

    result = run_validation_graph(logs, file_path=file_path)
    return jsonify(result)








@app.route("/")
def index():
    return """
<!DOCTYPE html>
<html lang="pt-BR">
<head>
    <meta charset="UTF-8">
    <title>Automation Code Validator</title>
    <style>
        * { box-sizing: border-box; }
        body { font-family: "Segoe UI", Arial, sans-serif; margin: 0; background: #f4f6f9; color: #222; }
        header { background: #1e3a5f; color: #fff; padding: 16px 24px; }
        header h1 { margin: 0; font-size: 20px; }
        main { max-width: 960px; margin: 24px auto; padding: 0 16px; }
        .card { background: #fff; border: 1px solid #d8dee7; border-radius: 8px; padding: 16px; margin-bottom: 16px; }
        .card h2 { font-size: 16px; margin: 0 0 12px; color: #1e3a5f; }
        textarea, input { width: 100%; padding: 8px; border: 1px solid #cbd2dd; border-radius: 6px; font-size: 13px; }
        textarea { min-height: 140px; font-family: Consolas, monospace; }
        button { background: #1e3a5f; color: #fff; border: 0; border-radius: 6px; padding: 10px 14px; margin-top: 10px; cursor: pointer; font-size: 14px; }
        button:hover { background: #2c5282; }
        pre { background: #0f172a; color: #e2e8f0; padding: 12px; border-radius: 6px; white-space: pre-wrap; word-break: break-word; font-size: 12px; max-height: 420px; overflow: auto; }
        .muted { color: #64748b; font-size: 13px; }
    </style>
</head>
<body>
    <header><h1>Automation Code Validator</h1></header>
    <main>
        <div class="card">
            <h2>1. Browser automation logs</h2>
            <textarea id="logs" placeholder="Paste Cypress, Selenium, or Playwright logs here..."></textarea>
            <button onclick="runPipeline()">Executar Pipeline</button>
            <p class="muted">O grafo roda: parser &rarr; evaluator &rarr; (fixer | END).</p>
        </div>
        <div class="card">
            <h2>2. Resultado</h2>
            <pre id="result">Aguardando execu&ccedil;&atilde;o...</pre>
        </div>
        <div class="card">
            <h2>3. Configura&ccedil;&atilde;o (Ollama)</h2>
            <label class="muted">Host</label>
            <input id="host" value="http://localhost:11434">
            <label class="muted">Modelo</label>
            <select id="model"></select>
            <button onclick="loadModels()">Atualizar Modelos</button>
            <button onclick="saveConfig()">Salvar Configura&ccedil;&atilde;o</button>
        </div>
    </main>
    <script>
        function runPipeline() {
            document.getElementById("result").textContent = "Executando pipeline...";
            fetch("/api/run", {
                method: "POST",
                headers: {"Content-Type": "application/json"},
                body: JSON.stringify({logs: document.getElementById("logs").value})
            })
            .then(r => r.json())
            .then(data => { document.getElementById("result").textContent = JSON.stringify(data, null, 2); })
            .catch(err => { document.getElementById("result").textContent = "Erro: " + err; });
        }
        function saveConfig() {
            fetch("/api/config", {
                method: "POST",
                headers: {"Content-Type": "application/json"},
                body: JSON.stringify({
                    host: document.getElementById("host").value,
                    model: document.getElementById("model").value
                })
            })
            .then(r => r.json())
            .then(data => { alert(data.message || "Configuracao salva."); });
        }
        function loadModels() {
            fetch("/api/models").then(r => r.json()).then(data => {
                const select = document.getElementById("model");
                select.innerHTML = "";
                (data.models || []).forEach(name => {
                    const opt = document.createElement("option");
                    opt.value = name;
                    opt.textContent = name;
                    select.appendChild(opt);
                });
                fetch("/api/config").then(r => r.json()).then(cfg => {
                    if (cfg.model && !select.querySelector(`option[value="${cfg.model}"]`)) {
                        const opt = document.createElement("option");
                        opt.value = cfg.model;
                        opt.textContent = cfg.model + " (n&atilde;o instalado?)";
                        select.appendChild(opt);
                    }
                    select.value = cfg.model;
                });
            });
        }
        loadModels();
    </script>
</body>
</html>
"""

# ---------------------------------------------------------------------------
# API routes
# ---------------------------------------------------------------------------
def _state_to_json(state: Dict) -> Dict:
    """Make the final GraphState JSON-serializable for the API response."""
    result = {}
    for key, value in state.items():
        if isinstance(value, list) and value and hasattr(value[0], "model_dump"):
            result[key] = [_anomaly_fields(item) for item in value]
        elif hasattr(value, "model_dump"):
            result[key] = value.model_dump()
        else:
            result[key] = value
    return result


@app.route("/api/run", methods=["POST"])
def api_run():
    payload = request.get_json(silent=True) or {}
    logs = payload.get("logs", "")
    if not logs.strip():
        return jsonify({"error": "Nenhum log fornecido."}), 400

    try:
        final_state = GRAPH.invoke(_initial_state(logs))
    except Exception as exc:  # report any pipeline failure to the UI
        return jsonify({"error": f"Falha ao executar o pipeline: {exc}"}), 500
    return jsonify(_state_to_json(final_state))


@app.route("/api/models", methods=["GET"])
def api_models():
    """List the models installed on the Ollama server (/api/tags)."""
    client = _make_client()
    return jsonify({"models": client.list_models(), "selected": client.model})


@app.route("/api/config", methods=["GET"])
def api_config_get():
    cfg = load_config()
    return jsonify({
        "host": cfg["ollama"]["host"],
        "model": cfg["ollama"]["model"],
    })


@app.route("/api/config", methods=["POST"])
def api_config_post():
    payload = request.get_json(silent=True) or {}
    cfg = load_config()
    if payload.get("host"):
        cfg["ollama"]["host"] = payload["host"]
    if payload.get("model"):
        cfg["ollama"]["model"] = payload["model"]
    save_config(cfg)
    return jsonify({"message": "Configuração salva.", "config": cfg})

def _initial_state(
    raw_logs: str,
    file_path: Optional[str] = None,
    source_code: Optional[str] = None,
) -> Dict:
    """Build the initial GraphState for a pipeline run."""
    return {
        "raw_cypress_logs": raw_logs,
        "framework": "Unknown",
        "language": "Unknown",
        "current_file_path": file_path,
        "source_code": source_code,
        "detected_anomalies": [],
        "evaluation_metrics": {},
        "retry_count": 0,
        "needs_fix": False,
        "fix_suggestion": None,
        "verification_logs": [],
        "execution_history": [],
        "current_node": "parser",
    }



# ---------------------------------------------------------------------------
# CLI mode
# ---------------------------------------------------------------------------
def run_cli() -> int:
    """Run the graph once against the log files in the configured folder (no Web UI)."""
    import logging

    logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(message)s")
    input_path = get_input_path()
    if os.path.isfile(input_path):
        log_paths = [input_path]
    elif os.path.isdir(input_path):
        log_paths = sorted(
            os.path.join(input_path, name)
            for name in os.listdir(input_path)
            if name.lower().endswith(".txt")
            and os.path.isfile(os.path.join(input_path, name))
        )
    else:
        print(f"Pasta/arquivo de logs não encontrado: {input_path}")
        return 1

    if not log_paths:
        print(f"Nenhum arquivo .txt encontrado em: {input_path}")
        return 1

    file_contents = []
    for path in log_paths:
        try:
            with open(path, "r", encoding="utf-8") as f:
                file_contents.append((path, f.read()))
        except OSError as exc:
            print(f"Erro ao ler {path}: {exc}")
            return 1

    try:
        final_states = [
            GRAPH.invoke(_initial_state(raw_logs, file_path=path))
            for path, raw_logs in file_contents
        ]
    except Exception as exc:
        print(f"Erro ao executar o grafo: {exc}")
        return 1

    print("\n=== HISTÓRICO DA EXECUÇÃO ===")
    for path, final_state in zip(log_paths, final_states):
        print(f"\n--- {os.path.basename(path)} ---")
        for entry in final_state.get("execution_history", []):
            print(f"[{entry['timestamp']}] {entry['node']}: {entry['message']}")

    print("\n=== ANOMALIAS DETECTADAS ===")
    for path, final_state in zip(log_paths, final_states):
        print(f"\n--- {os.path.basename(path)} ---")
        for anomaly in final_state.get("detected_anomalies", []):
            fields = _anomaly_fields(anomaly)
            print(f"- {fields.get('id')}: {fields.get('description')} "
                  f"(severidade: {fields.get('severity')}, flakiness: {fields.get('flakiness_score')})")

        print(f"needs_fix: {final_state.get('needs_fix')}")
        if final_state.get("needs_fix"):
            print("=== SUGESTÃO DE CORREÇÃO ===")
            print(final_state.get("fix_suggestion"))
    return 0


if __name__ == "__main__":
    cli_parser = argparse.ArgumentParser(description="Cypress LangGraph Validator")
    cli_parser.add_argument(
        "--cli",
        action="store_true",
        help="Run the pipeline once in the terminal (no Web UI).",
    )
    cli_args = cli_parser.parse_args()

    if cli_args.cli:
        sys.exit(run_cli())

    print("Iniciando servidor Flask em http://localhost:5000 ...")
    app.run(host="0.0.0.0", port=5000, debug=False)


