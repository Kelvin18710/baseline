# 批量流程（重构后）

## 入口脚本

- `tools/scan_complexity.py`
- `tools/run_batch_coverage.py`
- `tools/run_batch_parallel.py`
- `tools/aggregate_coverage.py`

## 1) 扫描 CC 方法池

```bash
python3 tools/scan_complexity.py \
  --project Lang \
  --threshold 2
```

输出：`data/complexity/Lang_stable_cc.csv`

## 2) 批量跑覆盖率

```bash
python3 tools/run_batch_coverage.py \
  --project Lang \
  --method-filter-mode signature
```

输出：

- `reports/batch/coverage/<Project>/<Project>_stable_coverage.csv`
- `reports/batch/logs/<Project>/`
- `reports/batch/artifacts/<Project>/`

覆盖率 CSV 除百分比外，还包含分子/分母字段：

- `line_cov_num`, `line_cov_den`
- `instr_cov_num`, `instr_cov_den`
- `branch_cov_num`, `branch_cov_den`

这样可直接做总体加权覆盖率统计。

默认行为：

- 不传 `--sampled-csv` 时，会先自动生成 `data/complexity/<Project>_stable_cc.csv`。
- 自动筛选阈值固定为 `cc>=2`，确保至少筛到有分支的方法再批量执行。
- 默认 `--time-limit=0`，即使用 EvoSuite 自身默认时间设置。

## 3) 并行加速

```bash
python3 tools/run_batch_parallel.py \
  --workers 8 \
  --project Lang
```

## 4) 覆盖率聚合

```bash
python3 tools/aggregate_coverage.py --project Lang
```

## 常用参数

- `--max-methods`：限制处理数量（调试）
- `--start-index`：断点续跑
- `--skip-existing`：跳过已记录方法
- `--no-fallback`：禁用类级回退
- `--sampled-csv`：使用采样方法集（如 `data/sampled_methods.csv`）
