#!/usr/bin/env bash
set -Eeuo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

if git_root="$(git -C "${SCRIPT_DIR}" rev-parse --show-toplevel 2>/dev/null)"; then
  DEFAULT_PROJECT_ROOT="${git_root}"
else
  DEFAULT_PROJECT_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"
fi

: "${PLOTSRV_PROJECT_ROOT:=${DEFAULT_PROJECT_ROOT}}"

: "${INSTALL_SOURCE:=wheel}" # wheel | testpypi | pypi | local
: "${WHEEL_PATH:=}"
: "${PACKAGE_NAME:=plotsrv}"
: "${PACKAGE_VERSION:=}"

: "${HOST:=0.0.0.0}"
: "${PORT:=8222}"
: "${WAIT_SECONDS:=30}"

: "${BASE_TEST_DIR:=$HOME/temp_testing}"
: "${UV_PYTHON:=3.11}"

: "${KEEP_TEST_DIR:=0}"
: "${SMOKE_CHECKS:=1}"
: "${LOG_TO_FILE:=1}"
: "${REMOVE_PLOTSRV_STATE_DIR:=1}"
: "${SERVER_READY_ATTEMPTS:=30}"

: "${GENERATE_COUNT:=3}"
: "${GENERATE_SLEEP_SECONDS:=1}"

: "${TEXT_VIEW_LABEL:=text}"
: "${CSV_VIEW_LABEL:=csv}"
: "${WATCH_SECTION:=static-files}"

: "${CONFIG_PATH:=$BASE_TEST_DIR/plotsrv.yml}"
CONFIG_WAS_EXPLICIT=0

: "${USE_PLOTSRV_EXAMPLES_REPO:=0}"
: "${PLOTSRV_EXAMPLES_REPO_URL:=https://github.com/anees-hill/plotsrv-examples.git}"
: "${TEST_APP_SCRIPT:=}"
: "${TEST_APP_ARGS:=}"

TIMESTAMP="$(date '+%Y%m%d-%H%M%S')"
TEST_DIR="${BASE_TEST_DIR}/test-${TIMESTAMP}"
PID_FILE="${TEST_DIR}/plotsrv.pid"
PGID_FILE="${TEST_DIR}/plotsrv.pgid"
LOG_FILE="${TEST_DIR}/plotsrv.log"

PLOTSRV_URL="http://127.0.0.1:${PORT}"
PLOTSRV_STATE_DIR="${BASE_TEST_DIR}/.plotsrv"
EXAMPLES_DIR="${TEST_DIR}/plotsrv-examples"

CMD=()
TEST_APP_ARGS_ARRAY=()
SMOKE_FAILURES=0

info() {
  printf '[INFO] %s\n' "$*"
}

warn() {
  printf '[WARN] %s\n' "$*" >&2
}

fail() {
  printf '[ERROR] %s\n' "$*" >&2
  exit 1
}

section() {
  printf '\n[SECTION] %s\n' "$*"
}

require_cmd() {
  command -v "$1" >/dev/null 2>&1 || fail "Required command not found: $1"
}

bool_is_true() {
  case "${1:-0}" in
    1|true|TRUE|yes|YES|y|Y) return 0 ;;
    *) return 1 ;;
  esac
}

refresh_paths_after_base_dir_change() {
  TEST_DIR="${BASE_TEST_DIR}/test-${TIMESTAMP}"
  PID_FILE="${TEST_DIR}/plotsrv.pid"
  PGID_FILE="${TEST_DIR}/plotsrv.pgid"
  LOG_FILE="${TEST_DIR}/plotsrv.log"
  PLOTSRV_STATE_DIR="${BASE_TEST_DIR}/.plotsrv"
  EXAMPLES_DIR="${TEST_DIR}/plotsrv-examples"
}

refresh_url_after_port_change() {
  PLOTSRV_URL="http://127.0.0.1:${PORT}"
}

parse_test_app_args() {
  TEST_APP_ARGS_ARRAY=()

  if [[ -z "${TEST_APP_ARGS}" ]]; then
    return 0
  fi

  local parsed
  parsed="$(
    python - "$TEST_APP_ARGS" <<'PY'
import shlex
import sys

for arg in shlex.split(sys.argv[1]):
    print(arg)
PY
  )"

  while IFS= read -r arg; do
    [[ -n "${arg}" ]] && TEST_APP_ARGS_ARRAY+=("${arg}")
  done <<< "${parsed}"
}

print_array_command() {
  printf '[INFO] Command:'
  printf ' %q' "$@"
  printf '\n'
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --mode|--install-source)
      INSTALL_SOURCE="$2"
      shift 2
      ;;
    --config)
      CONFIG_PATH="$2"
      CONFIG_WAS_EXPLICIT=1
      shift 2
      ;;
    --wheel-path)
      WHEEL_PATH="$2"
      shift 2
      ;;
    --package-name)
      PACKAGE_NAME="$2"
      shift 2
      ;;
    --package-version)
      PACKAGE_VERSION="$2"
      shift 2
      ;;
    --wait)
      WAIT_SECONDS="$2"
      shift 2
      ;;
    --host)
      HOST="$2"
      shift 2
      ;;
    --port)
      PORT="$2"
      refresh_url_after_port_change
      shift 2
      ;;
    --base-test-dir)
      BASE_TEST_DIR="$2"
      refresh_paths_after_base_dir_change
      shift 2
      ;;
    --uv-python)
      UV_PYTHON="$2"
      shift 2
      ;;
    --keep-test-dir)
      KEEP_TEST_DIR=1
      shift
      ;;
    --no-smoke-checks)
      SMOKE_CHECKS=0
      shift
      ;;
    --use-examples)
      USE_PLOTSRV_EXAMPLES_REPO=1
      shift
      ;;
    --examples-repo-url)
      PLOTSRV_EXAMPLES_REPO_URL="$2"
      shift 2
      ;;
    --test-app-script)
      TEST_APP_SCRIPT="$2"
      shift 2
      ;;
    --test-app-args)
      TEST_APP_ARGS="$2"
      shift 2
      ;;
    --project-root)
      PLOTSRV_PROJECT_ROOT="$2"
      shift 2
      ;;
    --help|-h)
      cat <<'EOF'
Usage:

  tests/smoke-test.sh [options]

Examples:

  tests/smoke-test.sh \
    --mode local \
    --use-examples \
    --test-app-script "src/smoke-tests/basic-smoke-test.py" \
    --test-app-args "--publisher-module smoke_tests.python_objs --publisher-delay 5" \
    --config plotsrv.yml \
    --wait 300 \
    --host 0.0.0.0 \
    --port 8998

Options:

  --mode local|wheel|testpypi|pypi
  --install-source local|wheel|testpypi|pypi
  --config PATH
  --wheel-path PATH
  --package-name NAME
  --package-version VERSION
  --wait SECONDS
  --host HOST
  --port PORT
  --base-test-dir PATH
  --uv-python VERSION
  --keep-test-dir
  --no-smoke-checks
  --use-examples
  --examples-repo-url URL
  --test-app-script PATH
  --test-app-args "ARGS PASSED TO TEST APP SCRIPT"
  --project-root PATH
EOF
      exit 0
      ;;
    *)
      fail "Unknown argument: $1"
      ;;
  esac
done

wait_for_http() {
  local url="$1"
  local attempts="${2:-30}"

  for ((i=1; i<=attempts; i++)); do
    if curl -fsS "${url}" >/dev/null 2>&1; then
      info "Endpoint ready: ${url}"
      return 0
    fi
    sleep 1
  done

  return 1
}

_smoke_fail() {
  local msg="$1"
  warn "$msg"
  ((SMOKE_FAILURES+=1))
  return 0
}

smoke_get() {
  local label="$1"
  local url="$2"

  if curl -fsS "${url}" >/dev/null 2>&1; then
    info "OK: ${label}"
  else
    _smoke_fail "FAILED: ${label} -> ${url}"
  fi
}

smoke_status_is() {
  local label="$1"
  local url="$2"
  local expected="$3"

  local actual
  actual="$(curl -s -o /dev/null -w '%{http_code}' "${url}" || true)"

  if [[ "${actual}" == "${expected}" ]]; then
    info "OK: ${label} (status ${actual})"
  else
    _smoke_fail "FAILED: ${label} -> expected ${expected}, got ${actual} (${url})"
  fi
}

smoke_status_in() {
  local label="$1"
  local url="$2"
  shift 2
  local allowed=("$@")

  local actual
  actual="$(curl -s -o /dev/null -w '%{http_code}' "${url}" || true)"

  for status in "${allowed[@]}"; do
    if [[ "${actual}" == "${status}" ]]; then
      info "OK: ${label} returned acceptable status ${actual}"
      return 0
    fi
  done

  _smoke_fail "FAILED: ${label} -> got ${actual}, expected one of: ${allowed[*]} (${url})"
}

smoke_body_contains() {
  local label="$1"
  local url="$2"
  local needle="$3"

  local body
  body="$(curl -fsS "${url}" 2>/dev/null || true)"

  if [[ -n "${body}" ]] && grep -Fq "${needle}" <<<"${body}"; then
    info "OK: ${label} contains '${needle}'"
  else
    _smoke_fail "FAILED: ${label} -> body missing '${needle}' (${url})"
  fi
}

smoke_header_contains() {
  local label="$1"
  local url="$2"
  local needle="$3"

  local headers
  headers="$(curl -sSI "${url}" 2>/dev/null || true)"

  if [[ -n "${headers}" ]] && grep -Fiq "${needle}" <<<"${headers}"; then
    info "OK: ${label} header contains '${needle}'"
  else
    _smoke_fail "FAILED: ${label} -> headers missing '${needle}' (${url})"
  fi
}

smoke_json_field_present() {
  local label="$1"
  local url="$2"
  local needle="$3"

  local body
  body="$(curl -fsS "${url}" 2>/dev/null || true)"

  if [[ -n "${body}" ]] && grep -Fq "\"${needle}\"" <<<"${body}"; then
    info "OK: ${label} has JSON field '${needle}'"
  else
    _smoke_fail "FAILED: ${label} -> JSON missing field '${needle}' (${url})"
  fi
}

smoke_post_json_status_is() {
  local label="$1"
  local url="$2"
  local json_payload="$3"
  local expected="$4"

  local actual
  actual="$(
    curl -s -o /dev/null -w '%{http_code}' \
      -X POST \
      -H 'Content-Type: application/json' \
      -d "${json_payload}" \
      "${url}" || true
  )"

  if [[ "${actual}" == "${expected}" ]]; then
    info "OK: ${label} (status ${actual})"
  else
    _smoke_fail "FAILED: ${label} -> expected ${expected}, got ${actual} (${url})"
  fi
}

install_plotsrv() {
  case "${INSTALL_SOURCE}" in
    local)
      [[ -d "${PLOTSRV_PROJECT_ROOT}" ]] || fail "PLOTSRV_PROJECT_ROOT does not exist: ${PLOTSRV_PROJECT_ROOT}"
      [[ -f "${PLOTSRV_PROJECT_ROOT}/pyproject.toml" ]] || fail "No pyproject.toml found at project root: ${PLOTSRV_PROJECT_ROOT}"

      info "Installing local plotsrv from: ${PLOTSRV_PROJECT_ROOT}"
      uv pip install -e "${PLOTSRV_PROJECT_ROOT}"
      ;;
    wheel)
      [[ -n "${WHEEL_PATH}" ]] || fail "INSTALL_SOURCE=wheel but WHEEL_PATH is empty"
      [[ -f "${WHEEL_PATH}" ]] || fail "Wheel file not found: ${WHEEL_PATH}"
      info "Installing from wheel: ${WHEEL_PATH}"
      uv pip install "${WHEEL_PATH}"
      ;;
    testpypi)
      if [[ -n "${PACKAGE_VERSION}" ]]; then
        info "Installing ${PACKAGE_NAME}==${PACKAGE_VERSION} from TestPyPI"
        uv pip install \
          --index-url https://test.pypi.org/simple/ \
          --extra-index-url https://pypi.org/simple \
          "${PACKAGE_NAME}==${PACKAGE_VERSION}"
      else
        info "Installing latest ${PACKAGE_NAME} from TestPyPI"
        uv pip install \
          --index-url https://test.pypi.org/simple/ \
          --extra-index-url https://pypi.org/simple \
          "${PACKAGE_NAME}"
      fi
      ;;
    pypi)
      if [[ -n "${PACKAGE_VERSION}" ]]; then
        info "Installing ${PACKAGE_NAME}==${PACKAGE_VERSION} from PyPI"
        uv pip install "${PACKAGE_NAME}==${PACKAGE_VERSION}"
      else
        info "Installing latest ${PACKAGE_NAME} from PyPI"
        uv pip install "${PACKAGE_NAME}"
      fi
      ;;
    *)
      fail "Unsupported INSTALL_SOURCE: ${INSTALL_SOURCE}"
      ;;
  esac
}

post_install_checks() {
  section "Post-install checks"

  python -V
  command -v python
  command -v plotsrv

  python - <<'PY'
import plotsrv
print("plotsrv imported from:", plotsrv.__file__)
print("plotsrv version:", getattr(plotsrv, "__version__", "<no __version__>"))
PY

  plotsrv --help >/dev/null
  plotsrv run --help >/dev/null

  info "Post-install checks passed"
}

write_fixture_files() {
  section "Writing fixture files"

  cat > text.txt <<'EOF'
hello from smoke test
second line
EOF

  cat > data.csv <<'EOF'
name,value
alpha,1
beta,2
gamma,3
EOF

  cat > sample.html <<'EOF'
<!doctype html>
<html>
  <body>
    <h1>Smoke HTML</h1>
    <p><strong>formatted</strong> content</p>
  </body>
</html>
EOF
}

write_main_py() {
  section "Writing main.py"

  cat > main.py <<EOF
from __future__ import annotations

import os
import time

import matplotlib.pyplot as plt
import pandas as pd
from plotsrv import plot, table, plotsrv

HOST = os.getenv("PLOTSRV_HOST", "${HOST}")
PORT = int(os.getenv("PLOTSRV_PORT", "${PORT}"))
GENERATE_COUNT = int(os.getenv("PLOTSRV_GENERATE_COUNT", "${GENERATE_COUNT}"))
GENERATE_SLEEP_SECONDS = float(
    os.getenv("PLOTSRV_GENERATE_SLEEP_SECONDS", "${GENERATE_SLEEP_SECONDS}")
)

@plot(label="demo-plot", section="demo", host=HOST, port=PORT)
def demo_plot(iteration: int = 0):
    fig, ax = plt.subplots()
    x = [1, 2, 3, 4]
    y = [
        1 + iteration,
        4 + (iteration * 2),
        9 + iteration,
        16 + (iteration * 3),
    ]
    ax.plot(x, y, marker="o")
    ax.set_title(f"Smoke Test Plot #{iteration + 1}")
    ax.set_xlabel("x")
    ax.set_ylabel("y")
    return fig

@table(label="demo-table", section="demo", host=HOST, port=PORT)
def demo_table(iteration: int = 0):
    return pd.DataFrame(
        {
            "letter": ["a", "b", "c"],
            "number": [1 + iteration, 2 + iteration, 3 + iteration],
            "iteration": [iteration + 1, iteration + 1, iteration + 1],
        }
    )

@plotsrv(label="demo-html", section="demo", host=HOST, port=PORT)
def demo_html():
    return {"html": "<h2>HTML Smoke</h2><p><b>bold</b> and <i>italic</i></p>", "unsafe": True}

def main() -> None:
    demo_html()

    for iteration in range(GENERATE_COUNT):
        fig = demo_plot(iteration=iteration)
        if fig is not None:
            plt.close(fig)

        demo_table(iteration=iteration)

        if iteration < GENERATE_COUNT - 1:
            time.sleep(GENERATE_SLEEP_SECONDS)

if __name__ == "__main__":
    main()
EOF
}

clone_examples_repo() {
  section "Cloning plotsrv-examples"

  [[ -n "${TEST_APP_SCRIPT}" ]] || fail "--use-examples requires --test-app-script"

  info "Cloning via HTTPS: ${PLOTSRV_EXAMPLES_REPO_URL}"
  git clone "${PLOTSRV_EXAMPLES_REPO_URL}" "${EXAMPLES_DIR}"

  [[ -d "${EXAMPLES_DIR}" ]] || fail "Examples repo was not cloned: ${EXAMPLES_DIR}"
  [[ -f "${EXAMPLES_DIR}/${TEST_APP_SCRIPT}" ]] || fail "TEST_APP_SCRIPT not found: ${EXAMPLES_DIR}/${TEST_APP_SCRIPT}"
}

setup_examples_env() {
  section "Setting up plotsrv-examples environment"

  cd "${EXAMPLES_DIR}"

  [[ -f "pyproject.toml" ]] || fail "plotsrv-examples has no pyproject.toml at: ${EXAMPLES_DIR}"

  if [[ "${INSTALL_SOURCE}" == "local" ]]; then
    section "Linking local plotsrv for examples pyproject"

    rm -f "${TEST_DIR}/plotsrv"
    ln -s "${PLOTSRV_PROJECT_ROOT}" "${TEST_DIR}/plotsrv"

    info "Linked ${TEST_DIR}/plotsrv -> ${PLOTSRV_PROJECT_ROOT}"

    info "Running uv sync in examples repo"
    uv sync --python "${UV_PYTHON}"
  else
    info "Running uv sync in examples repo without local uv sources"
    uv sync --python "${UV_PYTHON}" --no-sources
  fi

  source "${EXAMPLES_DIR}/.venv/bin/activate"

  info "Installing plotsrv-examples editable without resolving dependencies again"
  uv pip install -e . --no-deps

  install_plotsrv
  post_install_checks
}

build_generated_cmd() {
  section "Building generated plotsrv command"

  CMD=(
    plotsrv run main.py
    --mode callable
    --keep-alive
    --host "${HOST}"
    --port "${PORT}"
    --watch text.txt
    --watch-label "${TEXT_VIEW_LABEL}"
    --watch-section "${WATCH_SECTION}"
    --watch data.csv
    --watch-label "${CSV_VIEW_LABEL}"
    --watch-section "${WATCH_SECTION}"
    --no-truncate
  )

  if [[ -n "${CONFIG_PATH}" && -f "${CONFIG_PATH}" ]]; then
    info "Using config file: ${CONFIG_PATH}"
    CMD+=(--config "${CONFIG_PATH}")
  elif [[ "${CONFIG_WAS_EXPLICIT}" == "1" ]]; then
    fail "Explicit --config path does not exist: ${CONFIG_PATH}"
  else
    info "No config file found at CONFIG_PATH='${CONFIG_PATH}', running without --config"
  fi
}

build_examples_cmd() {
  section "Building examples app command"

  parse_test_app_args

  CMD=(
    python "${TEST_APP_SCRIPT}"
  )

  if [[ "${#TEST_APP_ARGS_ARRAY[@]}" -gt 0 ]]; then
    CMD+=("${TEST_APP_ARGS_ARRAY[@]}")
  fi

  local has_host_arg=0
  local has_port_arg=0
  local has_config_arg=0

  for arg in "${TEST_APP_ARGS_ARRAY[@]}"; do
    [[ "${arg}" == "--host" ]] && has_host_arg=1
    [[ "${arg}" == "--port" ]] && has_port_arg=1
    [[ "${arg}" == "--config" ]] && has_config_arg=1
  done

  if [[ "${has_host_arg}" == "0" ]]; then
    CMD+=(--host "${HOST}")
  fi

  if [[ "${has_port_arg}" == "0" ]]; then
    CMD+=(--port "${PORT}")
  fi

  if [[ -n "${CONFIG_PATH}" && "${has_config_arg}" == "0" ]]; then
    if [[ "${CONFIG_WAS_EXPLICIT}" == "1" && ! -f "${EXAMPLES_DIR}/${CONFIG_PATH}" && ! -f "${CONFIG_PATH}" ]]; then
      fail "Explicit --config path does not exist in examples repo or current path: ${CONFIG_PATH}"
    fi
    CMD+=(--config "${CONFIG_PATH}")
  fi
}

start_process() {
  section "Starting smoke app"

  local run_dir="$1"
  local venv_dir="$2"

  if [[ "${LOG_TO_FILE}" == "1" ]]; then
    (
      cd "${run_dir}"
      source "${venv_dir}/bin/activate"
      exec setsid env \
        HOST="${HOST}" \
        PORT="${PORT}" \
        PLOTSRV_HOST="${HOST}" \
        PLOTSRV_PORT="${PORT}" \
        PLOTSRV_GENERATE_COUNT="${GENERATE_COUNT}" \
        PLOTSRV_GENERATE_SLEEP_SECONDS="${GENERATE_SLEEP_SECONDS}" \
        "${CMD[@]}" >> "${LOG_FILE}" 2>&1
    ) &
  else
    (
      cd "${run_dir}"
      source "${venv_dir}/bin/activate"
      exec setsid env \
        HOST="${HOST}" \
        PORT="${PORT}" \
        PLOTSRV_HOST="${HOST}" \
        PLOTSRV_PORT="${PORT}" \
        PLOTSRV_GENERATE_COUNT="${GENERATE_COUNT}" \
        PLOTSRV_GENERATE_SLEEP_SECONDS="${GENERATE_SLEEP_SECONDS}" \
        "${CMD[@]}"
    ) &
  fi

  local launcher_pid=$!
  echo "${launcher_pid}" > "${PID_FILE}"

  sleep 1

  local pgid=""
  pgid="$(ps -o pgid= -p "${launcher_pid}" 2>/dev/null | tr -d '[:space:]' || true)"
  echo "${pgid}" > "${PGID_FILE}"

  info "Smoke app launcher PID: ${launcher_pid}"
  if [[ -n "${pgid}" ]]; then
    info "Smoke app process group: ${pgid}"
  else
    warn "Could not determine process group from PID ${launcher_pid}"
  fi
}

stop_process() {
  set +e

  local pid=""
  local pgid=""

  [[ -f "${PID_FILE}" ]] && pid="$(cat "${PID_FILE}")"
  [[ -f "${PGID_FILE}" ]] && pgid="$(cat "${PGID_FILE}")"

  if [[ -n "${pgid}" ]]; then
    info "Stopping process group ${pgid}"
    kill -TERM "-${pgid}" 2>/dev/null || true

    for _ in {1..20}; do
      if kill -0 "-${pgid}" 2>/dev/null; then
        sleep 1
      else
        break
      fi
    done

    if kill -0 "-${pgid}" 2>/dev/null; then
      warn "Process group still alive, sending SIGKILL to -${pgid}"
      kill -KILL "-${pgid}" 2>/dev/null || true
    fi
  elif [[ -n "${pid}" ]]; then
    info "Stopping PID ${pid}"
    kill -TERM "${pid}" 2>/dev/null || true

    for _ in {1..20}; do
      if kill -0 "${pid}" 2>/dev/null; then
        sleep 1
      else
        break
      fi
    done

    if kill -0 "${pid}" 2>/dev/null; then
      warn "PID still alive, sending SIGKILL"
      kill -KILL "${pid}" 2>/dev/null || true
    fi
  fi
}

cleanup() {
  set +e

  stop_process

  if [[ "${REMOVE_PLOTSRV_STATE_DIR}" == "1" && -d "${PLOTSRV_STATE_DIR}" ]]; then
    info "Removing plotsrv state directory: ${PLOTSRV_STATE_DIR}"
    rm -rf "${PLOTSRV_STATE_DIR}"
  fi

  if [[ "${KEEP_TEST_DIR}" == "1" ]]; then
    info "Keeping test directory: ${TEST_DIR}"
  else
    info "Removing test directory: ${TEST_DIR}"
    rm -rf "${TEST_DIR}"
  fi
}
trap cleanup EXIT INT TERM

run_common_security_smoke_checks() {
  section "Smoke checks: security expectations"

  smoke_status_is "GET /docs should be off" "${PLOTSRV_URL}/docs" "404"
  smoke_status_is "GET /openapi.json should be off" "${PLOTSRV_URL}/openapi.json" "404"

  smoke_post_json_status_is \
    "POST /shutdown should be blocked/off" \
    "${PLOTSRV_URL}/shutdown" \
    '{}' \
    "404"

  smoke_post_json_status_is \
    "POST /publish should be blocked locally-only or by proxy" \
    "${PLOTSRV_URL}/publish" \
    '{"kind":"artifact","label":"x","section":"y","artifact_kind":"text","artifact":"hello"}' \
    "403"
}

run_generated_smoke_checks() {
  section "Smoke checks: generated mini-app"

  smoke_get "GET /" "${PLOTSRV_URL}/"
  smoke_status_is "GET /plot" "${PLOTSRV_URL}/plot?view=demo:demo-plot" "200"
  smoke_status_is "GET /table/data demo table" "${PLOTSRV_URL}/table/data?view=demo:demo-table" "200"
  smoke_status_is "GET /artifact demo html" "${PLOTSRV_URL}/artifact?view=demo:demo-html" "200"

  smoke_get "GET /?view=demo:demo-plot" "${PLOTSRV_URL}/?view=demo:demo-plot"
  smoke_get "GET /?view=demo:demo-table" "${PLOTSRV_URL}/?view=demo:demo-table"
  smoke_get "GET /?view=demo:demo-html" "${PLOTSRV_URL}/?view=demo:demo-html"

  smoke_status_is "GET /artifact watched text" "${PLOTSRV_URL}/artifact?view=${WATCH_SECTION}:${TEXT_VIEW_LABEL}" "200"
  smoke_status_is "GET /table/data watched csv" "${PLOTSRV_URL}/table/data?view=${WATCH_SECTION}:${CSV_VIEW_LABEL}" "200"

  smoke_status_is "GET /status" "${PLOTSRV_URL}/status" "200"
  smoke_json_field_present "GET /status has freshness" "${PLOTSRV_URL}/status" "freshness"
  smoke_json_field_present "GET /status has last_updated" "${PLOTSRV_URL}/status" "last_updated"

  smoke_status_is "GET /history demo plot" "${PLOTSRV_URL}/history?view=demo:demo-plot" "200"
  smoke_json_field_present "GET /history has snapshots" "${PLOTSRV_URL}/history?view=demo:demo-plot" "snapshots"

  smoke_body_contains "Demo plot page contains image tag" "${PLOTSRV_URL}/?view=demo:demo-plot" '<img id="plot"'
  smoke_body_contains "Demo table data contains column letter" "${PLOTSRV_URL}/table/data?view=demo:demo-table" '"letter"'
  smoke_body_contains "Watched csv contains alpha" "${PLOTSRV_URL}/table/data?view=${WATCH_SECTION}:${CSV_VIEW_LABEL}" 'alpha'
  smoke_body_contains "Watched text artifact contains hello" "${PLOTSRV_URL}/artifact?view=${WATCH_SECTION}:${TEXT_VIEW_LABEL}" 'hello'
  smoke_body_contains "HTML artifact preserves HTML iframe mode markers" "${PLOTSRV_URL}/artifact?view=demo:demo-html" 'unsafe_iframe'

  smoke_status_is "GET /table/export demo table" "${PLOTSRV_URL}/table/export?view=demo:demo-table" "200"
  smoke_header_contains "GET /table/export has attachment header" "${PLOTSRV_URL}/table/export?view=demo:demo-table" 'content-disposition: attachment;'

  run_common_security_smoke_checks
}

run_examples_smoke_checks() {
  section "Smoke checks: plotsrv-examples app"

  smoke_get "GET /" "${PLOTSRV_URL}/"

  smoke_status_is "GET /status" "${PLOTSRV_URL}/status" "200"
  smoke_json_field_present "GET /status has freshness" "${PLOTSRV_URL}/status" "freshness"
  smoke_json_field_present "GET /status has last_updated" "${PLOTSRV_URL}/status" "last_updated"

  smoke_status_in "GET /views" "${PLOTSRV_URL}/views" "200" "403" "404"

  run_common_security_smoke_checks
}

finish_smoke_checks() {
  if [[ "${SMOKE_FAILURES}" -eq 0 ]]; then
    info "Smoke checks completed with no failures"
  else
    warn "Smoke checks completed with ${SMOKE_FAILURES} failure(s)"
  fi
}

run_generated_flow() {
  section "Creating virtual environment"
  uv venv --python "${UV_PYTHON}"

  source "${TEST_DIR}/.venv/bin/activate"

  install_plotsrv
  post_install_checks
  write_fixture_files
  write_main_py
  build_generated_cmd
  print_array_command "${CMD[@]}"
  start_process "${TEST_DIR}" "${TEST_DIR}/.venv"
}

run_examples_flow() {
  clone_examples_repo
  setup_examples_env
  build_examples_cmd
  print_array_command "${CMD[@]}"
  start_process "${EXAMPLES_DIR}" "${EXAMPLES_DIR}/.venv"
}

main() {
  require_cmd uv
  require_cmd curl
  require_cmd mkdir
  require_cmd date
  require_cmd ps
  require_cmd setsid
  require_cmd grep
  require_cmd python

  if bool_is_true "${USE_PLOTSRV_EXAMPLES_REPO}"; then
    require_cmd git
  fi

  mkdir -p "${BASE_TEST_DIR}"
  mkdir -p "${TEST_DIR}"

  info "Created test directory: ${TEST_DIR}"
  info "plotsrv project root: ${PLOTSRV_PROJECT_ROOT}"
  info "install source: ${INSTALL_SOURCE}"
  info "host: ${HOST}"
  info "port: ${PORT}"
  info "config path: ${CONFIG_PATH}"

  cd "${TEST_DIR}"

  if bool_is_true "${USE_PLOTSRV_EXAMPLES_REPO}"; then
    run_examples_flow
  else
    run_generated_flow
  fi

  section "Waiting for server to become ready"
  if ! wait_for_http "${PLOTSRV_URL}/" "${SERVER_READY_ATTEMPTS}"; then
    warn "Smoke app did not become ready in time"
    if [[ -f "${LOG_FILE}" ]]; then
      warn "Last 100 log lines:"
      tail -n 100 "${LOG_FILE}" || true
    fi
    exit 1
  fi

  if [[ "${SMOKE_CHECKS}" == "1" ]]; then
    if bool_is_true "${USE_PLOTSRV_EXAMPLES_REPO}"; then
      run_examples_smoke_checks
    else
      run_generated_smoke_checks
    fi

    finish_smoke_checks
  fi

  section "Idle wait"
  info "Sleeping for ${WAIT_SECONDS} seconds"
  sleep "${WAIT_SECONDS}"

  info "Job completed successfully"
}

main "$@"
