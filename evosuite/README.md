# EvoSuite Baseline（重构版）

本目录已按“工具 / 数据 / 报告 / 缓存”重组，目标是：入口统一、路径稳定、结果可追溯。

## 新目录结构

```text
evosuite/
  README.md
  tools/
    extract_method_list.py    # 提取方法列表（method_FEN）
    run.py                   # 单类/单方法：EvoSuite + JaCoCo
    scan_complexity.py       # 扫描 stable 源码圈复杂度
    run_batch_coverage.py    # 批量跑覆盖率
    run_batch_parallel.py    # 并行分发批量任务
    aggregate_coverage.py    # 覆盖率聚合
  data/
    sampled_methods.csv      # 采样方法列表（原 Sampled_Dataset_For_All_Projects.csv）
    method_lists/            # 方法清单（历史）
    samples/                 # 其他采样数据（历史）
  reports/
    batch/                   # 批量执行产物（coverage/logs/artifacts）
    method_coverage/         # 历史结果（原 result/）
  data/
    complexity/              # CC 扫描结果
  cache/
    lib/                     # 依赖 jar 缓存
    project_archives/        # 项目源码压缩包缓存
    project_workspace/       # 解压/构建后的工作目录
```

## 新命令用法

### 1) 单方法运行

```bash
python3 tools/run.py \
  --project Lang \
  --time-limit 60 \
  --target-class org.apache.commons.lang3.math.NumberUtils \
  --target-method createNumber

说明：
- `--time-limit` 控制传给 EvoSuite 的 `search_budget` 和 `global_timeout`（秒）。
- 当 `--time-limit<=0` 时，不设置这两个参数，使用 EvoSuite 自身默认值。
```

### 2) 扫描复杂度（生成方法池）

```bash
python3 tools/scan_complexity.py \
  --project Lang \
  --threshold 2
```

默认输出：
- `data/complexity/Lang_stable_cc.csv`

### 2.5) 提取 method_FEN 列表（可选）

```bash
python3 tools/extract_method_list.py \
  --project Lang \
  --min-cc 10
```

默认输出：
- `data/method_lists/Lang_cc10.csv`

### 3) 批量跑覆盖率

```bash
python3 tools/run_batch_coverage.py \
  --project Lang \
  --method-filter-mode signature
```

默认输出：
- 覆盖率汇总：`reports/batch/coverage/<Project>/<Project>_stable_coverage.csv`
- 运行日志：`reports/batch/logs/<Project>/`
- 测试产物：`reports/batch/artifacts/<Project>/`

CSV 中会同时保存：
- 百分比：`line_cov / instr_cov / branch_cov`
- 分子分母：`line_cov_num/line_cov_den`、`instr_cov_num/instr_cov_den`、`branch_cov_num/branch_cov_den`

说明：
- 若不传 `--sampled-csv`，脚本会自动生成 `data/complexity/<Project>_stable_cc.csv`。
- 自动筛选固定为 `cc>=2`，即至少保留 1 个分支的候选方法。
- 默认 `--time-limit=0`，即使用 EvoSuite 自身默认时间设置。

### 4) 并行批量运行

```bash
python3 tools/run_batch_parallel.py \
  --workers 8 \
  --project Lang
```

### 5) 聚合统计

```bash
python3 tools/aggregate_coverage.py \
  --project Lang
```

### 6) 清理所有产物

```bash
# 默认清理：reports/* 产物 + data/complexity + cache/project_workspace
python3 tools/clean_artifacts.py

# 仅预览将删除哪些路径
python3 tools/clean_artifacts.py --dry-run

# 彻底清理（额外删除依赖和源码缓存）
python3 tools/clean_artifacts.py --all-cache
```

## 迁移说明

- 旧入口 `new_run.py` 已移除，统一使用 `tools/run.py`。
- 原 `scripts/*.py` 已整体迁移到 `tools/` 并统一命名。
- 原 `result/` 已迁移到 `reports/method_coverage/`。
- 运行产物统一写入 `reports/`，下载和构建缓存统一放入 `cache/`。

## 支持项目与版本（JDK8 可用配置）

- `Lang` -> `org.apache.commons:commons-lang3:3.18.0`
- `Math` -> `org.apache.commons:commons-math3:3.6.1`
- `Cli` -> `commons-cli:commons-cli:1.6.0`
- `Codec` -> `commons-codec:commons-codec:1.21.0`
- `Collections` -> `org.apache.commons:commons-collections4:4.5.0`
- `CSV` -> `org.apache.commons:commons-csv:1.13.0`
- `Compress` -> `org.apache.commons:commons-compress:1.28.0`
- `JCore` -> `com.fasterxml.jackson.core:jackson-core:2.19.0`
- `JDataBind` -> `com.fasterxml.jackson.core:jackson-databind:2.19.0`
- `JXML` -> `com.fasterxml.jackson.dataformat:jackson-dataformat-xml:2.19.0`
- `JxPath` -> `commons-jxpath:commons-jxpath:1.4.0`
- `JodaTime` -> `joda-time:joda-time:2.13.1`

## 离线预下载（推荐先执行）

```bash
# 预下载全部项目 + 运行所需依赖到 cache/
python3 tools/prefetch_offline_assets.py --projects all

# 仅预下载部分项目
python3 tools/prefetch_offline_assets.py --projects Lang,Math,CSV
```

预下载后：
- 运行脚本会优先使用 `cache/project_archives` 的本地压缩包（支持 `.jar/.zip/.tar.gz`）
- 对应 binary jar 在 `cache/lib` 存在时会直接解压使用，不再在线拉取项目工件
