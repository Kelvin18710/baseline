# Baseline Randoop + JaCoCo

结构化的 Randoop 测试生成和覆盖率统计框架。

## 目录结构

```
randoop/
  tools/                         # 执行脚本
    run.py                       # 单方法测试生成 + 覆盖率计算
    run_batch_coverage.py        # 批量方法处理（按 CC CSV）
    run_batch_parallel.py        # 多进程并行执行包装
    scan_complexity.py           # 从源代码扫描圈复杂度
    aggregate_coverage.py        # 聚合覆盖率结果
    extract_method_list.py       # 提取项目方法列表
    clean_artifacts.py           # 清理工件和缓存
    prefetch_offline_assets.py   # 离线资源预取
  
  data/
    complexity/                  # CC CSV（包含方法列表）
    method_lists/                # 方法签名列表
  
  reports/
    batch/                       # 批处理输出（coverage_*.csv, logs/）
    method_coverage/             # 历史覆盖率报告
  
  cache/
    lib/                         # JAR 文件（二进制 + 源代码）
    project_archives/            # 项目源代码存档（.jar 格式）
    project_workspace/           # 解压/编译的项目树
```

## 支持的项目

- Lang, Math, Cli, Codec, Collections, CSV, Compress
- JCore, JDataBind, JXML, JxPath, JodaTime

## 快速开始

### 1. 预取离线资源（可选，用于网络不好的环境）

```bash
cd tools

# 下载所有项目和依赖
python3 prefetch_offline_assets.py --projects all

# 或者只下载特定项目
python3 prefetch_offline_assets.py --projects Lang,Math
```

### 2. 扫描圈复杂度

从源代码识别高圈复杂度的方法：

```bash
# 扫描 Lang 项目（CC >= 2）
python3 scan_complexity.py --project Lang --threshold 2

# 输出：data/complexity/Lang_stable_cc.csv
```

### 3. 单个方法测试

为特定类的特定方法生成测试并计算覆盖率：

```bash
python3 run.py \
  --project Lang \
  --class org.apache.commons.lang3.ArrayUtils \
  --method add \
  --time-limit 10

# 输出：
#   reports/method_coverage/Lang/org/apache/commons/lang3/ArrayUtils/
#   - jacoco.xml (JaCoCo 覆盖率报告)
#   - tests/ (生成的测试源代码)
```

### 4. 批量处理

对 CC CSV 中的所有方法进行测试（顺序执行）：

```bash
# 处理 Lang 的全部方法
python3 run_batch_coverage.py --project Lang

# 只处理前 50 个方法（用于快速测试）
python3 run_batch_coverage.py --project Lang --max-methods 50

# 输出：reports/batch/coverage_Lang.csv
```

CSV 格式（包含分子/分母用于精确总体统计）：

```
class_fqcn,method_name,line_cov,instr_cov,branch_cov,line_cov_num,line_cov_den,instr_cov_num,instr_cov_den,branch_cov_num,branch_cov_den
org.apache.commons.lang3.ArrayUtils,add,45.00,50.00,30.00,90,200,100,200,60,200
...
```

### 5. 并行处理

使用多个 worker 加速批处理：

```bash
# 4 个 worker 并行处理
python3 run_batch_parallel.py --workers 4 --project Lang

# 或者带方法限制
python3 run_batch_parallel.py --workers 8 --project Lang --max-methods 100
```

### 6. 聚合覆盖率

计算批处理结果的总体覆盖率（通过分子/分母精确计算）：

```bash
python3 aggregate_coverage.py --project Lang

# 输出：汇总的行/指令/分支覆盖率
```

### 7. 多项目批处理

对多个项目进行完整的批处理：

```bash
for p in Lang Math Cli Codec Collections CSV Compress JCore JDataBind JXML JxPath JodaTime; do
  echo "Processing $p..."
  python3 scan_complexity.py --project $p
  python3 run_batch_parallel.py --workers 8 --project $p
  python3 aggregate_coverage.py --project $p
done
```

## 清理

### 查看将删除的内容

```bash
python3 clean_artifacts.py --dry-run
```

### 保留离线资源，只清理报告和工作区

```bash
python3 clean_artifacts.py
```

### 完全清理（包括下载的 JAR 文件）

```bash
python3 clean_artifacts.py --all-cache
```

## 配置

所有脚本使用以下默认值：

- **时间限制**：Randoop 默认 10 秒
- **圈复杂度阈值**：2（包括至少 1 个分支的方法）
- **JaCoCo 版本**：0.8.8
- **Randoop 版本**：4.3.0
- **JUnit 版本**：4.13.2

要修改这些，编辑各脚本中的常量定义。

## 注意

1. **覆盖率统计的准确性**：CSV 中包含分子/分母字段，使得总体覆盖率计算比使用百分比更准确
2. **离线友好**：所有依赖都可以预先下载，支持网络环境不稳定的场景
3. **可重复性**：使用固定的 Maven 坐标和 Randoop seed=42 保证结果可重现
