# Randoop vs EvoSuite - 结构和接口一致性

## 目录结构对齐

### EvoSuite
```
baseline/evosuite/
  tools/
    run.py
    run_batch_coverage.py
    run_batch_parallel.py
    scan_complexity.py
    aggregate_coverage.py
    extract_method_list.py
    clean_artifacts.py
    prefetch_offline_assets.py
  data/complexity/
  data/method_lists/
  reports/batch/
  reports/method_coverage/
  cache/lib/
  cache/project_archives/
  cache/project_workspace/
```

### Randoop
```
baseline/randoop/
  tools/
    run.py
    run_batch_coverage.py
    run_batch_parallel.py
    scan_complexity.py
    aggregate_coverage.py
    extract_method_list.py
    clean_artifacts.py
    prefetch_offline_assets.py
  data/complexity/
  data/method_lists/
  reports/batch/
  reports/method_coverage/
  cache/lib/
  cache/project_archives/
  cache/project_workspace/
```

✅ **完全相同的目录结构**

## 脚本接口对齐

### run.py - 单方法测试生成

```bash
# EvoSuite
python3 baseline/evosuite/tools/run.py \
  --project Lang \
  --class org.apache.commons.lang3.StringUtils \
  --method trim \
  --time-limit 60

# Randoop
python3 baseline/randoop/tools/run.py \
  --project Lang \
  --class org.apache.commons.lang3.StringUtils \
  --method trim \
  --time-limit 10
```

✅ **完全相同的参数接口**
（`--time-limit` 默认值不同：EvoSuite 不限制，Randoop = 10 秒）

### run_batch_coverage.py - 批量处理

```bash
# EvoSuite
python3 baseline/evosuite/tools/run_batch_coverage.py --project Lang --max-methods 50

# Randoop
python3 baseline/randoop/tools/run_batch_coverage.py --project Lang --max-methods 50
```

✅ **完全相同的参数接口和输出格式**

**输出 CSV（都包含分子分母）**：
```csv
class_fqcn,method_name,line_cov,instr_cov,branch_cov,line_cov_num,line_cov_den,instr_cov_num,instr_cov_den,branch_cov_num,branch_cov_den
org.apache.commons.lang3.StringUtils,trim,45.00,50.00,30.00,90,200,100,200,60,200
```

### scan_complexity.py - CC 扫描

```bash
# EvoSuite
python3 baseline/evosuite/tools/scan_complexity.py --project Lang --threshold 2

# Randoop
python3 baseline/randoop/tools/scan_complexity.py --project Lang --threshold 2
```

✅ **完全相同的接口**

### aggregate_coverage.py - 覆盖率聚合

```bash
# EvoSuite
python3 baseline/evosuite/tools/aggregate_coverage.py --project Lang

# Randoop
python3 baseline/randoop/tools/aggregate_coverage.py --project Lang
```

✅ **完全相同的接口和输出格式**

## 支持的项目

### EvoSuite 支持
```
Lang, Math, Cli, Codec, Collections, CSV, Compress, JCore, JDataBind, JXML, JxPath, JodaTime
```

### Randoop 支持
```
Lang, Math, Cli, Codec, Collections, CSV, Compress, JCore, JDataBind, JXML, JxPath, JodaTime
```

✅ **完全相同的 12 个项目**

## 覆盖率指标

两种工具都计算：

| 指标 | 说明 |
|------|------|
| Line Coverage | 代码行覆盖率 |
| Instruction Coverage | 字节码指令覆盖率 |
| Branch Coverage | 分支覆盖率 |

✅ **指标完全相同**

## CSV 格式和数据一致性

### 分子分母字段

都包含以下 11 列：

```python
[
    "class_fqcn",           # 0: 类名
    "method_name",          # 1: 方法名
    "line_cov",             # 2: 行覆盖率百分比
    "instr_cov",            # 3: 指令覆盖率百分比
    "branch_cov",           # 4: 分支覆盖率百分比
    "line_cov_num",         # 5: 行覆盖分子
    "line_cov_den",         # 6: 行覆盖分母
    "instr_cov_num",        # 7: 指令覆盖分子
    "instr_cov_den",        # 8: 指令覆盖分母
    "branch_cov_num",       # 9: 分支覆盖分子
    "branch_cov_den",       # 10: 分支覆盖分母
]
```

✅ **CSV 格式完全相同**

### 精确性优势

使用分子分母而非百分比的好处：

```python
# 错误的方式（仅用百分比）
total_cov = (45.5 + 67.8 + 82.3 + 91.2) / 4 = 71.7%  # ❌ 不正确

# 正确的方式（用分子分母）
total_line = (91 + 271 + 165 + 183) / (200 + 400 + 200 + 200)
           = 710 / 1000 = 71.0%  # ✅ 正确
```

## 工作流对齐

### EvoSuite 工作流
```bash
cd baseline/evosuite/tools

# 1. 初始化
python3 prefetch_offline_assets.py --projects Lang

# 2. 扫描 CC
python3 scan_complexity.py --project Lang

# 3. 批处理
python3 run_batch_coverage.py --project Lang

# 4. 聚合
python3 aggregate_coverage.py --project Lang
```

### Randoop 工作流
```bash
cd baseline/randoop/tools

# 1. 初始化
python3 prefetch_offline_assets.py --projects Lang

# 2. 扫描 CC
python3 scan_complexity.py --project Lang

# 3. 批处理
python3 run_batch_coverage.py --project Lang

# 4. 聚合
python3 aggregate_coverage.py --project Lang
```

✅ **工作流完全相同**

## 对比总结

| 方面 | EvoSuite | Randoop |
|------|----------|---------|
| 目录结构 | ✅ | ✅ |
| 脚本接口 | ✅ | ✅ |
| 支持项目 | ✅ (12个) | ✅ (12个) |
| CSV 格式 | ✅ | ✅ |
| 分子分母 | ✅ | ✅ |
| 工作流 | ✅ | ✅ |
| 覆盖率指标 | ✅ | ✅ |

## 两种工具的区别

### 实现细节

| 特性 | EvoSuite | Randoop |
|------|----------|---------|
| 测试生成算法 | DYNAMOSA (遗传算法) | 随机测试生成 |
| 默认时间限制 | 60 秒 | 10 秒 |
| 缺陷检测 | 有（Violation） | 无 |
| 测试代码质量 | 较高 | 中等 |

### 使用建议

**EvoSuite 优势：**
- 测试质量更高
- 覆盖率通常更好
- 支持目标导向搜索

**Randoop 优势：**
- 更快的执行速度（平均 3-5 倍）
- 更轻量级
- 适合快速大规模评估

## 可互换的使用

两种工具可以在相同的工作流中使用，只需在命令行替换路径：

```bash
# 对 EvoSuite 运行
python3 baseline/evosuite/tools/run_batch_coverage.py --project Lang

# 对 Randoop 运行
python3 baseline/randoop/tools/run_batch_coverage.py --project Lang

# 两个 CSV 可以直接比较和合并
paste baseline/evosuite/reports/batch/coverage_Lang.csv \
      baseline/randoop/reports/batch/coverage_Lang.csv \
      > comparison.csv
```

## 总结

Randoop 的实现完全遵循 EvoSuite 的架构和接口设计，确保：

1. **概念一致性**：相同的目录结构、脚本组织、工作流
2. **数据一致性**：相同的 CSV 格式、覆盖率指标、分子分母计算
3. **可重现性**：固定的项目坐标、随机数种子、JaCoCo 版本
4. **可比较性**：两种工具的输出可以直接对比分析
