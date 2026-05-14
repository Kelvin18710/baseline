#!/usr/bin/env bash
set -euo pipefail

# EvoSuite 服务器批量运行脚本
# 用法：在仓库根目录运行：
#   bash ./evosuite/tools/run_server_cc_ge2_batch.sh
#
# 路径约定：
# - 所有可配置目录都写相对路径，不写机器相关的绝对路径。
# - 脚本会自动切到仓库根目录，输出 CSV 中的路径字段也会写成仓库相对路径。
#
# 筛选口径：
# - 项目：下面 PROJECTS 中列出的 stable 版本项目。
# - 方法：cc >= 2。
# - 访问级别：不过滤 public/protected/private/package-private。
# - 构造器：包含。
# - 生成方式：默认只做方法级生成，不回退到类级生成，保证不同方法之间口径一致。
#
# 并行说明：
# - 每个 worker 独立使用一个 workdir 后缀，避免并行覆盖工作目录。
# - 每个项目内部并行，项目之间顺序执行，方便定位问题。
# - WORKERS=12 是比较稳的起点；确认服务器资源足够后再调大。

PROJECTS=(Lang Math CSV Cli Collections Codec)
WORKERS=12
TIME_LIMIT=20
NO_FALLBACK=1

OUT_DIR="./evosuite/reports/batch_cc_ge2/coverage"
LOG_DIR="./evosuite/reports/batch_cc_ge2/logs"
ARTIFACT_DIR="./evosuite/reports/batch_cc_ge2/artifacts"
WORKER_STDOUT_DIR="./evosuite/reports/batch_cc_ge2/worker_stdout"
COMPLEXITY_DIR="./evosuite/reports/batch_cc_ge2/complexity"
NOHUP_LOG_DIR="./evosuite/reports/batch_cc_ge2/nohup_logs"

# 重新跑时是否清理旧 summary/log/artifact。
# 1 = 清理后全量重跑；0 = 保留 summary，脚本默认会跳过已有条目。
CLEAN_BEFORE_RUN=1

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"
cd "${REPO_ROOT}"

mkdir -p "${OUT_DIR}" "${LOG_DIR}" "${ARTIFACT_DIR}" "${WORKER_STDOUT_DIR}" "${COMPLEXITY_DIR}" "${NOHUP_LOG_DIR}"

echo "[INFO] projects: ${PROJECTS[*]}"
echo "[INFO] workers: ${WORKERS}"
echo "[INFO] time limit: ${TIME_LIMIT}"
echo "[INFO] no fallback: ${NO_FALLBACK}"

for project in "${PROJECTS[@]}"; do
  echo "===== ${project}: prepare cc >= 2 method list ====="

  if [[ "${CLEAN_BEFORE_RUN}" == "1" ]]; then
    echo "[INFO] clean previous outputs for ${project}"
    rm -rf "${OUT_DIR}/${project}" "${LOG_DIR}/${project}" "${ARTIFACT_DIR}/${project}" "${WORKER_STDOUT_DIR}/${project}"
  fi

  mkdir -p "${WORKER_STDOUT_DIR}/${project}"

  python3 ./evosuite/tools/scan_complexity.py \
    --project "${project}" \
    --threshold 1 \
    --out-dir "${COMPLEXITY_DIR}" \
    --out-file "${project}_cc_ge_2.csv"

  echo "===== ${project}: run EvoSuite workers ====="
  for worker_id in $(seq 0 "$((WORKERS - 1))"); do
    extra_args=()
    if [[ "${NO_FALLBACK}" == "1" ]]; then
      extra_args+=(--no-fallback)
    fi

    python3 ./evosuite/tools/run_batch_coverage.py \
      --project "${project}" \
      --cc-csv "${COMPLEXITY_DIR}/${project}_cc_ge_2.csv" \
      --workers "${WORKERS}" \
      --worker-id "${worker_id}" \
      --time-limit "${TIME_LIMIT}" \
      --out-dir "${OUT_DIR}" \
      --log-dir "${LOG_DIR}" \
      --artifact-dir "${ARTIFACT_DIR}" \
      "${extra_args[@]}" \
      > "${WORKER_STDOUT_DIR}/${project}/worker_${worker_id}.log" 2>&1 &
  done
  wait

  echo "===== ${project}: aggregate ====="
  python3 ./evosuite/tools/aggregate_coverage.py \
    --project "${project}" \
    --csv "${OUT_DIR}/${project}/${project}_stable_coverage.csv" \
    > "${WORKER_STDOUT_DIR}/${project}/aggregate.log" 2>&1 || true
done

echo "===== all projects done ====="
find "${OUT_DIR}" -name '*_stable_coverage.csv' -exec wc -l {} \; | sort
