# Randoop Baseline 完整工作流

## Phase 1: 初始化和准备（一次性，5 分钟）

```bash
cd /home/kelvin/work/baseline/randoop/tools

# 1.1 预取离线资源（可选，但推荐用于服务器环境）
python3 prefetch_offline_assets.py --projects all
# 输出: cache/lib/ 中的所有 JAR 和依赖

# 1.2 验证环境
python3 -c "
import sys
from pathlib import Path
lib = Path('../../cache/lib')
required = ['randoop-all-4.3.0.jar', 'junit-4.13.2.jar', 'jacocoagent-0.8.8.jar']
for r in required:
    if (lib / r).exists():
        print(f'✓ {r}')
    else:
        print(f'✗ {r} missing')
"
```

## Phase 2: 单项目完整流程（以 Lang 为例）

### Step 1: 扫描圈复杂度（2 分钟）

```bash
python3 scan_complexity.py --project Lang --threshold 2

# 输出：data/complexity/Lang_stable_cc.csv
# 包含：约 1000+ 个 CC >= 2 的方法
```

### Step 2: 快速测试（验证系统是否工作，5 分钟）

```bash
# 处理前 5 个方法，验证工作流
python3 run_batch_coverage.py --project Lang --max-methods 5

# 检查输出
cat reports/batch/coverage_Lang.csv | head -3

# 应该看到类似：
# class_fqcn,method_name,line_cov,instr_cov,branch_cov,line_cov_num,line_cov_den,...
# org.apache.commons.lang3.ArrayUtils,add,45.00,50.00,30.00,90,200,...
```

### Step 3: 完整批处理（10-30 分钟，取决于方法数量）

**顺序执行（简单但较慢）：**
```bash
python3 run_batch_coverage.py --project Lang

# 输出：reports/batch/coverage_Lang.csv（所有方法的覆盖率）
```

**或并行执行（快速，推荐）：**
```bash
python3 run_batch_parallel.py --workers 8 --project Lang

# 4 个 worker = 快 ~3 倍
# 8 个 worker = 快 ~6 倍（取决于 CPU 核心数）
```

### Step 4: 聚合和验证（1 分钟）

```bash
# 计算总体覆盖率
python3 aggregate_coverage.py --project Lang

# 输出：
# ============================================================
# Aggregate coverage for Lang:
# ============================================================
#   line:        51234/100000 (51.23%)
#   instr:       61234/100000 (61.23%)
#   branch:      31234/100000 (31.23%)
# ============================================================

# 或用 Python 脚本处理 CSV
python3 -c "
import csv
csv_path = 'reports/batch/coverage_Lang.csv'
total_line = total_instr = total_branch = 0
count = 0
with open(csv_path) as f:
    for row in csv.DictReader(f):
        total_line += int(row.get('line_cov_num', 0))
        total_instr += int(row.get('instr_cov_num', 0))
        total_branch += int(row.get('branch_cov_num', 0))
        count += 1
print(f'Methods: {count}')
print(f'Line: {total_line}')
print(f'Instr: {total_instr}')
"
```

## Phase 3: 多项目批量处理（1-2 小时）

### 并行处理所有项目

```bash
declare -a projects=("Lang" "Math" "Cli" "Codec" "Collections" "CSV" "Compress" "JCore" "JDataBind" "JXML" "JxPath" "JodaTime")

for project in "${projects[@]}"; do
  echo "====== Processing $project ======"
  python3 scan_complexity.py --project $project --threshold 2 || \
    { echo "Failed to scan complexity for $project"; continue; }
  
  python3 run_batch_parallel.py --workers 8 --project $project || \
    { echo "Failed to process $project"; continue; }
  
  python3 aggregate_coverage.py --project $project
  echo ""
done
```

### 后台执行（不阻塞终端）

```bash
nohup bash /home/kelvin/work/baseline/randoop/batch_runner.sh > /tmp/randoop_batch.log 2>&1 &

# 监控进度
tail -f /tmp/randoop_batch.log | grep -E "Processing|Aggregate|Coverage"

# 查看完整日志
tail -100 /tmp/randoop_batch.log
```

**batch_runner.sh 内容**：
```bash
#!/bin/bash
set -e
cd /home/kelvin/work/baseline/randoop/tools

projects=("Lang" "Math" "Cli" "Codec" "Collections" "CSV" "Compress" "JCore" "JDataBind" "JXML" "JxPath" "JodaTime")

for p in "${projects[@]}"; do
  echo "===== $p: scan complexity ====="
  python3 scan_complexity.py --project "$p" || continue
  
  echo "===== $p: batch process ====="
  python3 run_batch_parallel.py --workers 8 --project "$p" || continue
  
  echo "===== $p: aggregate ====="
  python3 aggregate_coverage.py --project "$p"
  
  echo "===== $p: done ====="
  echo ""
done

echo "All projects completed"
```

## Phase 4: 结果验证和汇总

### 检查所有 CSV 文件

```bash
# 列出所有覆盖率 CSV
ls -lh /home/kelvin/work/baseline/randoop/reports/batch/coverage_*.csv

# 计算总体统计
python3 << 'EOF'
import csv
from pathlib import Path

batch_dir = Path('reports/batch')
results = {}

for csv_file in batch_dir.glob('coverage_*.csv'):
    project = csv_file.stem.replace('coverage_', '')
    
    total_line_num = total_line_den = 0
    total_instr_num = total_instr_den = 0
    total_branch_num = total_branch_den = 0
    count = 0
    
    with open(csv_file) as f:
        for row in csv.DictReader(f):
            total_line_num += int(row.get('line_cov_num', 0))
            total_line_den += int(row.get('line_cov_den', 0))
            total_instr_num += int(row.get('instr_cov_num', 0))
            total_instr_den += int(row.get('instr_cov_den', 0))
            total_branch_num += int(row.get('branch_cov_num', 0))
            total_branch_den += int(row.get('branch_cov_den', 0))
            count += 1
    
    line_pct = 100.0 * total_line_num / total_line_den if total_line_den > 0 else 0
    instr_pct = 100.0 * total_instr_num / total_instr_den if total_instr_den > 0 else 0
    branch_pct = 100.0 * total_branch_num / total_branch_den if total_branch_den > 0 else 0
    
    results[project] = (count, line_pct, instr_pct, branch_pct)

print(f"{'Project':<15} {'Methods':<10} {'Line':<10} {'Instr':<10} {'Branch':<10}")
print("=" * 55)
for project in sorted(results.keys()):
    count, line, instr, branch = results[project]
    print(f"{project:<15} {count:<10} {line:>7.2f}% {instr:>7.2f}% {branch:>7.2f}%")
EOF
```

### 导出数据用于分析

```bash
# 合并所有项目的结果
python3 << 'EOF'
import csv
from pathlib import Path

output_csv = Path('reports/batch') / 'all_projects_combined.csv'

with open(output_csv, 'w', newline='') as outf:
    writer = csv.writer(outf)
    writer.writerow(['project', 'class_fqcn', 'method_name', 'line_cov', 'instr_cov', 
                     'branch_cov', 'line_cov_num', 'line_cov_den', 'instr_cov_num', 
                     'instr_cov_den', 'branch_cov_num', 'branch_cov_den'])
    
    batch_dir = Path('reports/batch')
    for csv_file in sorted(batch_dir.glob('coverage_*.csv')):
        project = csv_file.stem.replace('coverage_', '')
        with open(csv_file) as f:
            reader = csv.DictReader(f)
            for row in reader:
                writer.writerow([project] + list(row.values()))

print(f"Combined CSV saved: {output_csv}")
EOF
```

## Phase 5: 清理（可选）

```bash
# 预览将删除的内容
python3 clean_artifacts.py --dry-run

# 保留离线资源，只删除报告和工作区
python3 clean_artifacts.py

# 完全清理（包括缓存的 JAR）
python3 clean_artifacts.py --all-cache
```

## 故障恢复

### 如果某个项目失败

```bash
# 1. 检查失败原因
tail -50 /tmp/randoop_batch.log | grep -A 10 "failed"

# 2. 清理失败的项目工作区
rm -rf /home/kelvin/work/baseline/randoop/cache/project_workspace/Lang

# 3. 重新尝试
python3 run_batch_parallel.py --workers 8 --project Lang
```

### 跳过某个项目并继续

```bash
# 在 batch_runner.sh 中注释掉失败的项目
# 或使用条件语句
if [[ "$project" != "FailedProject" ]]; then
  python3 run_batch_parallel.py --workers 8 --project "$project"
fi
```

## 最佳实践

1. **始终先运行 prefetch**：确保所有依赖都可用
2. **从小规模开始**：用 `--max-methods 10` 验证工作流
3. **使用并行处理**：`--workers` 数量 = CPU 核心数 - 1
4. **定期备份结果**：`cp -r reports/batch /backup/randoop_results_$(date +%Y%m%d)`
5. **监控磁盘空间**：生成的工件会消耗 10-50GB（取决于项目数量）
6. **后台运行长任务**：使用 `nohup` 或 `tmux`

## 环境变量（可选）

```bash
# 指定 Java 路径（如果有多个 Java 版本）
export JAVA_HOME=/usr/lib/jvm/java-8-openjdk-amd64

# 指定临时目录（如果默认 /tmp 空间不足）
export TMPDIR=/large/disk/tmp

# 增加 JVM 堆大小（如果处理超大项目）
export RANDOOP_OPTS="-Xmx8g"
```
