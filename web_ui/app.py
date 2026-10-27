from flask import Flask, Response, jsonify, render_template, request, stream_with_context
import os
import sys
import json
import datetime
import ipaddress
import threading
import uuid
from urllib.parse import urlsplit

import requests

# Adicionar o diretório raiz ao path para imports do src
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from src.main import check_ollama_ready, run_validation_graph, stream_validation_graph
from src.utils.config import get_input_path, get_prompt_path, load_config, save_config
from src.utils.llm_client import CancellationToken
from src.utils.technology_detector import detect_technology

app = Flask(__name__)

# Configurações
LOGS_DIR = os.path.abspath(os.path.join(os.getcwd(), "logs"))
active_runs = {}
active_runs_lock = threading.Lock()


def _build_anomaly_summary(data, file_path=None, raw_logs=""):
    evaluations = (data.get("evaluation_metrics") or {}).get("evaluations") or []
    evaluations_by_id = {
        evaluation.get("anomaly_id"): evaluation
        for evaluation in evaluations
        if evaluation.get("anomaly_id") is not None
    }
    fix_suggestion = data.get("fix_suggestion")
    anomalies = []

    for anomaly in data.get("detected_anomalies") or []:
        fields = anomaly.model_dump() if hasattr(anomaly, "model_dump") else dict(anomaly)
        evaluation = evaluations_by_id.get(fields.get("id"))
        needs_fix = bool(evaluation and evaluation.get("needs_fix"))
        suggestion = fix_suggestion if needs_fix else None
        if needs_fix:
            status = "fix_suggested" if suggestion else "fix_needed"
        else:
            status = "evaluated" if evaluation else "detected"

        anomalies.append({
            "id": fields.get("id"),
            "description": fields.get("description", ""),
            "status": status,
            "file_path": fields.get("file_path"),
            "corrected": False,
            "needs_fix": needs_fix,
            "evaluation": evaluation,
            "fix_suggestion": suggestion,
        })

    source_path = file_path or next(
        (
            anomaly.get("file_path")
            for anomaly in (data.get("detected_anomalies") or [])
            if (anomaly.get("file_path") if isinstance(anomaly, dict) else getattr(anomaly, "file_path", None))
        ),
        None,
    )
    framework = data.get("framework") or data.get("framework_type") or "Unknown"
    language = data.get("language") or "Unknown"
    if framework == "Unknown" or language == "Unknown":
        detected_framework, detected_language = detect_technology(
            raw_logs, file_path=source_path
        )
        if framework == "Unknown":
            framework = detected_framework
        if language == "Unknown":
            language = detected_language

    return {
        "file_name": os.path.basename(source_path) if source_path else "Unknown",
        "file_path": source_path,
        "framework": framework,
        "framework_type": framework,
        "language": language,
        "anomaly_count": len(anomalies),
        "needs_fix": any(anomaly["needs_fix"] for anomaly in anomalies),
        "anomalies": anomalies,
    }

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/api/logs', methods=['GET'])
def get_logs():
    try:
        page = max(1, int(request.args.get("page", "1")))
    except ValueError:
        return jsonify({"error": "Page must be a positive integer."}), 400

    page_size = 5
    log_files = []
    if os.path.isdir(LOGS_DIR):
        for filename in os.listdir(LOGS_DIR):
            if not filename.lower().endswith(".json"):
                continue

            path = os.path.join(LOGS_DIR, filename)
            try:
                file_stat = os.stat(path)
            except OSError:
                continue

            if os.path.isfile(path):
                log_files.append((file_stat.st_mtime, {
                    "filename": filename,
                    "created_time": datetime.datetime.fromtimestamp(
                        file_stat.st_mtime
                    ).strftime("%Y-%m-%d %H:%M:%S"),
                    "size_bytes": file_stat.st_size,
                }))

    log_files.sort(key=lambda item: item[0], reverse=True)
    total = len(log_files)
    start = (page - 1) * page_size
    logs = [item[1] for item in log_files[start:start + page_size]]

    return jsonify({
        "logs": logs,
        "page": page,
        "page_size": page_size,
        "total": total,
        "has_more": start + len(logs) < total,
    })

@app.route('/api/logs-details/<filename>', methods=['GET'])
def get_log_details(filename):
    """Retorna os detalhes completos de um arquivo de log específico"""
    if os.path.exists(LOGS_DIR):
        path = os.path.join(LOGS_DIR, filename)
        try:
            with open(path, 'r', encoding='utf-8') as f:
                data = json.load(f)
                file_stat = os.stat(path)
                created_time = datetime.datetime.fromtimestamp(file_stat.st_mtime)
                return jsonify({
                    "filename": filename,
                    "content": data,
                    "created_time": created_time.strftime("%Y-%m-%d %H:%M:%S"),
                    "size_bytes": file_stat.st_size
                })
        except Exception as e:
            return jsonify({"error": str(e)}), 500
    return jsonify({"error": f"Arquivo não encontrado: {filename}"}), 404

@app.route('/api/run', methods=['POST'])
def run_validation():
    input_path = get_input_path()
    if os.path.isfile(input_path):
        log_paths = [input_path]
    elif os.path.isdir(input_path):
        try:
            log_paths = sorted(
                os.path.join(input_path, name)
                for name in os.listdir(input_path)
                if name.lower().endswith(".txt")
                and os.path.isfile(os.path.join(input_path, name))
            )
        except OSError as error:
            return jsonify({"status": "error", "message": str(error)}), 500
    else:
        return jsonify({
            "status": "error",
            "message": f"Input folder or file was not found: {input_path}",
        }), 404

    if not log_paths:
        return jsonify({
            "status": "empty",
            "message": f"No .txt files found in the input folder: {input_path}",
        })

    summary = []
    try:
        for path in log_paths:
            with open(path, "r", encoding="utf-8") as log_file:
                raw_logs = log_file.read()
            result = run_validation_graph(raw_logs, file_path=path)
            if not result.get("success"):
                return jsonify({
                    "status": "error",
                    "message": result.get("error", f"Validation failed for {path}."),
                }), 500
            summary.append(
                _build_anomaly_summary(result.get("data", {}), path, raw_logs)
            )
    except (OSError, UnicodeError) as error:
        return jsonify({"status": "error", "message": f"Unable to read input file: {error}"}), 500
    except Exception as error:
        return jsonify({"status": "error", "message": str(error)}), 500

    os.makedirs(LOGS_DIR, exist_ok=True)
    timestamp = datetime.datetime.now()
    while True:
        filename = f"verification_summary_{timestamp.strftime('%Y%m%d_%H%M%S')}.json"
        log_path = os.path.join(LOGS_DIR, filename)
        try:
            with open(log_path, "x", encoding="utf-8") as log_file:
                json.dump(summary, log_file, indent=2, ensure_ascii=False)
            break
        except FileExistsError:
            timestamp += datetime.timedelta(seconds=1)
        except OSError as error:
            return jsonify({"status": "error", "message": f"Unable to save result log: {error}"}), 500

    return jsonify({
        "status": "success",
        "message": f"Inspection completed. Results saved to {filename}.",
        "filename": filename,
        "files_processed": len(log_paths),
        "anomalies_found": sum(block["anomaly_count"] for block in summary),
    })

@app.route('/api/run-stream', methods=['POST'])
def run_validation_stream():
    run_id = request.headers.get("X-Run-ID") or uuid.uuid4().hex
    cancellation_token = CancellationToken()
    with active_runs_lock:
        active_runs[run_id] = cancellation_token

    def event_stream():
        def send_event(event):
            return f"data: {json.dumps(event, ensure_ascii=False)}\n\n"

        yield send_event({
            "type": "progress",
            "message": "[START] Scanning the configured input folder...",
        })

        input_path = get_input_path()
        if os.path.isfile(input_path):
            log_paths = [input_path]
        elif os.path.isdir(input_path):
            try:
                log_paths = sorted(
                    os.path.join(input_path, name)
                    for name in os.listdir(input_path)
                    if name.lower().endswith(".txt")
                    and os.path.isfile(os.path.join(input_path, name))
                )
            except OSError as error:
                yield send_event({"type": "error", "message": str(error)})
                return
        else:
            yield send_event({
                "type": "error",
                "message": f"Input folder or file was not found: {input_path}",
            })
            return

        if not log_paths:
            yield send_event({
                "type": "empty",
                "message": f"No .txt files found in the input folder: {input_path}",
            })
            return

        yield send_event({
            "type": "progress",
            "message": f"[FILES] Found {len(log_paths)} input file(s).",
        })

        log_contents = []
        for index, path in enumerate(log_paths, start=1):
            yield send_event({
                "type": "progress",
                "message": f"[READ] Loading file {index}/{len(log_paths)}: {os.path.basename(path)}",
            })
            try:
                with open(path, "r", encoding="utf-8") as log_file:
                    log_contents.append((path, log_file.read()))
            except (OSError, UnicodeError) as error:
                yield send_event({
                    "type": "error",
                    "message": f"Unable to read {os.path.basename(path)}: {error}",
                })
                return

        if cancellation_token.cancelled:
            yield send_event({"type": "cancelled", "message": "Inspection stopped by user."})
            return

        yield send_event({
            "type": "progress",
            "message": "[OLLAMA] Checking if Ollama is responding...",
        })
        try:
            ollama = check_ollama_ready()
        except Exception as error:
            yield send_event({
                "type": "error",
                "message": f"[OLLAMA] Not ready. Input was not sent: {error}",
            })
            return

        if ollama["used_fallback"]:
            yield send_event({
                "type": "progress",
                "message": (
                    f"[OLLAMA] Ollama Ready at {ollama['host']}. Configured model "
                    f"is unavailable; using {ollama['model']}. Sending "
                    f"{len(log_paths)} file(s) to validation."
                ),
            })
        else:
            yield send_event({
                "type": "progress",
                "message": (
                    f"[OLLAMA] Ollama Ready at {ollama['host']} with model "
                    f"{ollama['model']}. Sending {len(log_paths)} file(s) to validation."
                ),
            })

        if cancellation_token.cancelled:
            yield send_event({"type": "cancelled", "message": "Inspection stopped by user."})
            return

        summary = []
        for index, (file_path, raw_logs) in enumerate(log_contents, start=1):
            framework, _language = detect_technology(raw_logs, file_path=file_path)
            yield send_event({
                "type": "progress",
                "message": (
                    f"[PARSER] Processing {index}/{len(log_contents)}: "
                    f"{os.path.basename(file_path)} | Framework detected: {framework}."
                ),
            })
            graph_result = None
            for event in stream_validation_graph(
                raw_logs,
                file_path=file_path,
                cancellation_token=cancellation_token,
            ):
                if event["type"] == "cancelled":
                    yield send_event(event)
                    return
                if event["type"] == "result":
                    graph_result = event
                else:
                    yield send_event(event)

            if not graph_result or not graph_result.get("success"):
                yield send_event({
                    "type": "error",
                    "message": (
                        f"{os.path.basename(file_path)}: "
                        f"{(graph_result or {}).get('error', 'Validation failed.')}"
                    ),
                })
                return

            summary.append(
                _build_anomaly_summary(
                    graph_result.get("data", {}), file_path, raw_logs
                )
            )
            if cancellation_token.cancelled:
                yield send_event({"type": "cancelled", "message": "Inspection stopped by user."})
                return

        os.makedirs(LOGS_DIR, exist_ok=True)
        timestamp = datetime.datetime.now()
        while True:
            filename = f"verification_summary_{timestamp.strftime('%Y%m%d_%H%M%S')}.json"
            log_path = os.path.join(LOGS_DIR, filename)
            try:
                with open(log_path, "x", encoding="utf-8") as log_file:
                    json.dump(summary, log_file, indent=2, ensure_ascii=False)
                break
            except FileExistsError:
                timestamp += datetime.timedelta(seconds=1)
            except OSError as error:
                yield send_event({
                    "type": "error",
                    "message": f"Unable to save result log: {error}",
                })
                return

        yield send_event({
            "type": "complete",
            "message": f"Inspection completed. Results saved to {filename}.",
            "filename": filename,
            "files_processed": len(log_paths),
            "anomalies_found": sum(block["anomaly_count"] for block in summary),
        })

    response = Response(
        stream_with_context(event_stream()),
        mimetype="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
    response.call_on_close(lambda: _remove_active_run(run_id, cancellation_token))
    return response

@app.route('/api/run-cancel/<run_id>', methods=['POST'])
def cancel_validation_run(run_id):
    with active_runs_lock:
        cancellation_token = active_runs.get(run_id)
    if cancellation_token is None:
        return jsonify({"status": "not_found", "message": "No active inspection found."}), 404

    cancellation_token.cancel()
    return jsonify({"status": "cancelling", "message": "Cancellation requested."})

def _remove_active_run(run_id, cancellation_token):
    with active_runs_lock:
        if active_runs.get(run_id) is cancellation_token:
            active_runs.pop(run_id, None)

@app.route('/api/prompts', methods=['GET'])
def get_prompts():
    prompts = {}
    for prompt_type in ['evaluator', 'fixer']:
        file_path = get_prompt_path(prompt_type)
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                prompts[prompt_type] = f.read()
        except Exception as e:
            prompts[prompt_type] = ""
    return jsonify(prompts)

@app.route('/api/prompts', methods=['POST'])
def save_prompts():
    data = request.get_json()
    prompts = ['evaluator', 'fixer']
    for prompt_type in prompts:
        content = data.get(prompt_type)
        if content is not None:
            file_path = get_prompt_path(prompt_type)
            try:
                with open(file_path, 'w', encoding='utf-8') as f:
                    f.write(content)
            except Exception as e:
                return jsonify({"error": f"Erro ao salvar {prompt_type}: {str(e)}"}), 500
    
    return jsonify({"message": "Prompts salvos com sucesso!"})

@app.route('/api/config/input-path', methods=['GET'])
def get_config_input_path():
    config = load_config()
    return jsonify({"input_path": config["files"]["input_path"]})

@app.route('/api/config/input-path', methods=['POST'])
def save_config_input_path():
    data = request.get_json(silent=True) or {}
    input_path = data.get("input_path")
    if not isinstance(input_path, str) or not input_path.strip():
        return jsonify({"error": "Informe um diretório válido."}), 400

    config = load_config()
    config["files"]["input_path"] = input_path
    try:
        save_config(config)
    except OSError as error:
        return jsonify({"error": f"Erro ao salvar o diretório: {error}"}), 500

    return jsonify({"message": "Diretório salvo com sucesso!", "input_path": input_path})

def _validate_ollama_base_url(base_url):
    if not isinstance(base_url, str):
        raise ValueError("Informe uma URL válida para o Ollama.")

    parsed = urlsplit(base_url.strip())
    if (parsed.scheme not in ("http", "https") or not parsed.hostname
            or parsed.username or parsed.password or parsed.path not in ("", "/")
            or parsed.query or parsed.fragment):
        raise ValueError("Use uma URL base, como http://localhost:11434.")

    hostname = parsed.hostname.lower()
    if hostname != "localhost":
        try:
            if not ipaddress.ip_address(hostname).is_loopback:
                raise ValueError("Por segurança, o Ollama deve estar em localhost.")
        except ValueError as error:
            raise ValueError("Por segurança, o Ollama deve estar em localhost.") from error

    return f"{parsed.scheme}://{parsed.netloc}"

@app.route('/api/config/ollama', methods=['GET'])
def get_ollama_config():
    config = load_config()
    return jsonify({
        "preferred_model": config["ai"]["preferred_model"],
        "host": config["ollama"]["host"],
        "model": config["ollama"]["model"],
    })

@app.route('/api/config/ollama', methods=['POST'])
def save_ollama_config():
    data = request.get_json(silent=True) or {}
    preferred_model = data.get("preferred_model")
    if preferred_model != "ollama":
        return jsonify({
            "error": "Only Local LLM (Ollama) is currently integrated."
        }), 400

    config = load_config()
    config["ai"]["preferred_model"] = preferred_model
    if preferred_model == "ollama":
        try:
            config["ollama"]["host"] = _validate_ollama_base_url(data.get("host"))
        except ValueError as error:
            return jsonify({"error": str(error)}), 400

        model = data.get("model")
        if not isinstance(model, str) or not model.strip():
            return jsonify({"error": "Select an Ollama model."}), 400
        config["ollama"]["model"] = model.strip()

    try:
        save_config(config)
    except OSError as error:
        return jsonify({"error": f"Erro ao salvar a configuração: {error}"}), 500

    return jsonify({"message": "AI configuration saved successfully!"})

@app.route('/api/ollama/models', methods=['GET'])
def get_ollama_models():
    config = load_config()
    requested_url = request.args.get("host", config["ollama"]["host"])
    try:
        base_url = _validate_ollama_base_url(requested_url)
        response = requests.get(f"{base_url}/api/tags", timeout=10)
        response.raise_for_status()
        payload = response.json()
    except ValueError as error:
        return jsonify({"error": str(error)}), 400
    except requests.RequestException as error:
        return jsonify({"error": f"Não foi possível consultar o Ollama: {error}"}), 502

    models = payload.get("models", []) if isinstance(payload, dict) else []
    return jsonify({
        "models": [model["name"] for model in models if isinstance(model, dict) and model.get("name")],
    })


if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True)
