# Randoop Baseline 快速开始

## ⚡ 30 秒快速开始

```bash
cd /home/kelvin/work/baseline/randoop/tools

# 1. 预取资源（可选，第一次推荐）
python3 prefetch_offline_assets.py --projects Lang

# 2. 扫描圈复杂度
python3 scan_complexity.py --project Lang

# 3. 快速测试（前 10 个方法）
python3 run_batch_coverage.py --project Lang --max-methods 10

# 4. 查看结果
cat ../reports/batch/coverage_Lang.csv | head -5
```

## 📋 完整工作流（以 Lang 为例）

```bash
cd /home/kelvin/work/baseline/randoop/tools

# Step 1: 初始化（首次）
python3 prefetch_offline_assets.py --projects Lang
# ✓ 下载所有依赖到 cache/lib/

# Step 2: 扫描圈复杂度方法
python3 scan_complexity.py --project Lang --threshold 2
# ✓ 生成 data/complexity/Lang_stable_cc.csv

# Step 3: 并行批处理（4 个 worker）
python3 run_batch_parallel.py --workers 4 --project Lang
# ✓ 生成 reports/batch/coverage_Lang.csv

# Step 4: 聚合统计
python3 aggregate_coverage.py --project Lang
# ✓ 显示总体覆盖率
```

## 📊 生成的文件

执行后会在以下位置生成结果：

### CSV 数据（最重要）
```
reports/batch/
  └── coverage_Lang.csv          # 关键输出：所有方法的覆盖率
```

### 详细日志
```
reports/batch/
  └── logs/
      ├── org_apache_commons_lang3_StringUtils_trim.log
      ├── org_apache_commons_lang3_StringUtils_join.log
      └── ...
```

### 项目工作区（临时，可删除）
```
cache/project_workspace/
  └── Lang/                       # 临时编译和生成目录
      ├── bin/                    # .class 文件
      ├── src/                    # .java 源文件
      └── randoop-tests/          # 生成的测试
```

## 🔍 查看结果

```bash
# 查看前 5 行 CSV
head -5 reports/batch/coverage_Lang.csv

# 计数方法
wc -l reports/batch/coverage_Lang.csv

# 找最高覆盖率的 10 个方法
sort -t',' -k3 -rn reports/batch/coverage_Lang.csv | head -10

# 统计平均覆盖率
awk -F',' 'NR>1 {sum+=$3; count++} END {print "Average:", sum/count "%"}' \
  reports/batch/coverage_Lang.csv
```

## 🚀 性能优化

### 减少时间
```bash
# 只处理前 50 个方法（快速测试）
python3 run_batch_coverage.py --project Lang --max-methods 50

# 使用多个 worker（推荐）
python3 run_batch_parallel.py --workers 8 --project Lang
# workers = CPU核心数 - 1 最佳
```

### 适用于多个项目
```bash
# 一行命令处理所有项目
for p in Lang Math Cli Codec Collections CSV Compress JCore JDataBind JXML JxPath JodaTime; do
  echo "Processing $p..."
  python3 scan_complexity.py --project $p
  python3 run_batch_parallel.py --workers 4 --project $p
done
```

## 📝 CSV 列说明

```csv
class_fqcn          # 类的完全限定名
method_name         # 方法名
line_cov            # 行覆盖率百分比 (0-100)
instr_cov           # 指令覆盖率百分比 (0-100)
branch_cov          # 分支覆盖率百分比 (0-100)
line_cov_num        # 覆盖的行数
line_cov_den        # 总行数
instr_cov_num       # 覆盖的指令数
instr_cov_den       # 总指令数
branch_cov_num      # 覆盖的分支数
branch_cov_den      # 总分支数
```

## 💡 常见问题

### Q: 如何跳过预取重新使用本地资源？
```bash
# 直接运行，会自动使用 cache/ 中的资源
python3 run_batch_coverage.py --project Lang
```

### Q: CSV 中 line_cov_num / line_cov_den 是什么？
```
这是"分子分母"字段，用于精确计算总体覆盖率
分子 = 覆盖的行数
分母 = 总行数
百分比 = 分子/分母 * 100
```

### Q: 如何导出所有项目的合并结果？
```bash
python3 << 'EOF'
import csv
from pathlib import Path

output = open('all_results.csv', 'w', newline='')
writer = csv.writer(output)
writer.writerow(['project', 'class', 'method', 'line_cov', 'instr_cov', 'branch_cov', 'line_num', 'line_den', 'instr_num', 'instr_den', 'branch_num', 'branch_den'])

for csv_file in Path('reports/batch').glob('coverage_*.csv'):
    project = csv_file.stem.split('_')[1]
    with open(csv_file) as f:
        for i, row in enumerate(csv.reader(f)):
            if i == 0: continue
            writer.writerow([project] + row)

output.close()
print('Combined results in all_results.csv')
EOF
```

### Q: 如何清理临时文件但保留 CSV 结果？
```bash
python3 clean_artifacts.py
# 删除 reports/batch 日志
# 删除 cache/project_workspace 临时目录
# 保留 reports/batch/coverage_*.csv 和 cache/lib
```

## ✅ 检查清单

- [ ] 预取资源：`python3 prefetch_offline_assets.py --projects Lang`
- [ ] 扫描 CC：`python3 scan_complexity.py --project Lang`
- [ ] 快速测试：`python3 run_batch_coverage.py --project Lang --max-methods 5`
- [ ] 验证 CSV：`head -5 reports/batch/coverage_Lang.csv`
- [ ] 完整批处理：`python3 run_batch_parallel.py --workers 4 --project Lang`
- [ ] 查看结果：`python3 aggregate_coverage.py --project Lang`

## 📚 更多文档

- `README.md` - 完整说明和架构
- `workflow.md` - 详细工作流和多项目批处理
- `command_example.md` - 各种命令示例选项
- `CONSISTENCY.md` - 与 EvoSuite 的一致性说明

## 🆘 故障排除

### 错误：找不到 CC CSV
```bash
# 确保先运行了扫描
python3 scan_complexity.py --project Lang
# 检查生成的文件
ls -la data/complexity/
```

### 错误：Randoop JAR 不存在
```bash
# 预取或手动下载
python3 prefetch_offline_assets.py --projects all
# 或检查
ls -la cache/lib/randoop-all-4.3.0.jar
```

### 错误：权限被拒绝
```bash
# 给脚本添加执行权限
chmod +x tools/*.py
```

### 进程超时或卡住
```bash
# 查看后台进程
ps aux | grep python3

# 杀死进程
pkill -f "run_batch_coverage.py"

# 清理临时文件重新开始
rm -rf cache/project_workspace/Lang
```

## 📞 获取帮助

```bash
# 查看脚本帮助
python3 run.py --help
python3 run_batch_coverage.py --help
python3 scan_complexity.py --help

# 检查日志
tail -50 reports/batch/logs/*.log

# 测试环境
python3 -c "
import subprocess
print('Java:', subprocess.run(['java', '-version'], capture_output=True).stderr.decode()[:30])
print('Python:', subprocess.run(['python3', '--version'], capture_output=True).stdout.decode())
"
```
