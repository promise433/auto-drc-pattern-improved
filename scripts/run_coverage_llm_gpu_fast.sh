#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
cd "${REPO_ROOT}"

if [[ -n "${VIRTUAL_ENV:-}" ]]; then
  echo "[ENV] using active virtualenv: ${VIRTUAL_ENV}"
elif [[ -f ".venv-gpu/bin/activate" ]]; then
  echo "[ENV] activating ${REPO_ROOT}/.venv-gpu"
  source ".venv-gpu/bin/activate"
elif [[ -f ".venv/bin/activate" ]]; then
  echo "[ENV] activating ${REPO_ROOT}/.venv"
  source ".venv/bin/activate"
else
  echo "[ERR] no active virtualenv and neither .venv-gpu nor .venv exists"
  echo "[HINT] create one environment first, then install dependencies from requirements.txt"
  exit 1
fi

DEFAULT_FALLBACK_MODEL="TinyLlama/TinyLlama-1.1B-Chat-v1.0"
LOCAL_FALLBACK_MODEL="models/TinyLlama-1.1B-Chat-v1.0"
PREFERRED_LOCAL_LARGE_MODEL="models/Qwen2.5-7B-Instruct"
REQUESTED_MODEL="${AUTO_DRC_LLM_MODEL:-}"
if [[ -n "${REQUESTED_MODEL}" ]]; then
  LLM_MODEL="${REQUESTED_MODEL}"
elif [[ -d "${PREFERRED_LOCAL_LARGE_MODEL}" ]]; then
  LLM_MODEL="${PREFERRED_LOCAL_LARGE_MODEL}"
elif [[ -d "${LOCAL_FALLBACK_MODEL}" ]]; then
  LLM_MODEL="${LOCAL_FALLBACK_MODEL}"
else
  LLM_MODEL="${DEFAULT_FALLBACK_MODEL}"
fi

if [[ "${LLM_MODEL}" == models/* && ! -d "${LLM_MODEL}" ]]; then
  echo "[ERR] Requested local model directory not found: ${LLM_MODEL}"
  exit 5
fi

HF_ENDPOINT_VAL="${AUTO_DRC_HF_ENDPOINT:-}"
if [[ -z "${HF_ENDPOINT_VAL}" && "${LLM_MODEL}" != models/* && "${LLM_MODEL}" != /* ]]; then
  # Default to a reachable mirror for remote model IDs in this environment.
  HF_ENDPOINT_VAL="https://hf-mirror.com"
fi
if [[ -n "${HF_ENDPOINT_VAL}" ]]; then
  export HF_ENDPOINT="${HF_ENDPOINT_VAL}"
  echo "[HF] endpoint=${HF_ENDPOINT}"
fi

LLM_MAX_NEW_TOKENS="${AUTO_DRC_LLM_MAX_NEW_TOKENS:-128}"
LLM_GOOD_CANDIDATES="${AUTO_DRC_LLM_GOOD_CANDIDATES:-2}"
LLM_BAD_CANDIDATES="${AUTO_DRC_LLM_BAD_CANDIDATES:-3}"
LLM_ILLEGAL_CANDIDATES="${AUTO_DRC_LLM_ILLEGAL_CANDIDATES:-1}"
LLM_CANDIDATE_GROWTH="${AUTO_DRC_LLM_CANDIDATE_GROWTH:-1}"
LLM_MAX_CANDIDATES_PER_INTENT="${AUTO_DRC_LLM_MAX_CANDIDATES_PER_INTENT:-6}"
echo "[LLM] model=${LLM_MODEL}"
echo "[LLM] good=${LLM_GOOD_CANDIDATES} bad=${LLM_BAD_CANDIDATES} illegal=${LLM_ILLEGAL_CANDIDATES} growth=${LLM_CANDIDATE_GROWTH} max_per_intent=${LLM_MAX_CANDIDATES_PER_INTENT}"

python - <<'PY'
import ctypes
import re
import sys
from pathlib import Path

import torch

status = Path("/proc/self/status").read_text(encoding="utf-8", errors="ignore")
seccomp = re.search(r"^Seccomp:\s+(\d+)$", status, flags=re.MULTILINE)
no_new_privs = re.search(r"^NoNewPrivs:\s+(\d+)$", status, flags=re.MULTILINE)
seccomp_v = int(seccomp.group(1)) if seccomp else -1
nnp_v = int(no_new_privs.group(1)) if no_new_privs else -1

try:
    rc = ctypes.CDLL("libcuda.so.1").cuInit(0)
except OSError as exc:
    print(f"[ERR] Failed to load libcuda.so.1: {exc}")
    sys.exit(2)

print(f"[CUDA] cuInit rc={rc}, Seccomp={seccomp_v}, NoNewPrivs={nnp_v}")
if rc != 0:
    if rc == 304 and seccomp_v == 2:
        print("[HINT] CUDA is blocked by sandbox/seccomp. Run outside restricted sandbox.")
    sys.exit(3)

ok = torch.cuda.is_available()
print(f"[CUDA] torch={torch.__version__} available={ok} count={torch.cuda.device_count()}")
if not ok:
    print("[ERR] torch.cuda.is_available() is False.")
    sys.exit(4)
print(f"[CUDA] device0={torch.cuda.get_device_name(0)}")
PY

exec python -m autodrc.runset_coverage \
  --generator llm \
  --llm-model "${LLM_MODEL}" \
  --llm-max-new-tokens "${LLM_MAX_NEW_TOKENS}" \
  --llm-good-candidates "${LLM_GOOD_CANDIDATES}" \
  --llm-bad-candidates "${LLM_BAD_CANDIDATES}" \
  --llm-illegal-candidates "${LLM_ILLEGAL_CANDIDATES}" \
  --llm-candidate-growth "${LLM_CANDIDATE_GROWTH}" \
  --llm-max-candidates-per-intent "${LLM_MAX_CANDIDATES_PER_INTENT}" \
  "$@"
