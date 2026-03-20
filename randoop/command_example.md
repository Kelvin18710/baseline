# Randoop 常见命令示例

## 初始化（一次性）

### 1. 预取离线资源
```bash
cd /home/kelvin/work/baseline/randoop/tools

# 全部项目（约 500MB）
python3 prefetch_offline_assets.py --projects all

# 或只预取使用的项目
python3 prefetch_offline_assets.py --projects Lang,Math,Cli
```

**输出**：
- `cache/lib/`: 所有 JAR 文件（二进制 + 源代码）
- `cache/project_archives/`: 项目源代码备份

## 单个方法测试

### 生成测试并计算覆盖率
```bash
cd /home/kelvin/work/baseline/randoop/tools

python3 run.py \
  --project Lang \
  --class org.apache.commons.lang3.StringUtils \
  --method trim \
  --time-limit 10

# 输出：
# [+] line:        XXX/YYY (P.PP%)
# [+] instr:       XXX/YYY (P.PP%)
# [+] branch:      XXX/YYY (P.PP%)
# [+] Artifacts saved to reports/method_coverage/Lang/...
```

**参数**：
- `--project`: 项目名称
- `--class`: 完全限定类名（必需）
- `--method`: 方法名（可选，用于过滤测试）
- `--time-limit`: 秒数（0 = Randoop 默认 10 秒）
- `--no-artifacts`: 不保存报告

## 批量处理

### 1. 扫描圈复杂度（第一步）
```bash
python3 scan_complexity.py --project Lang --threshold 2

# 输出：data/complexity/Lang_stable_cc.csv
# 包含：1000+ 个 CC >= 2 的方法
```

### 2. 批量生成测试（顺序）
```bash
# 处理全部方法
python3 run_batch_coverage.py --project Lang

# 或只处理前 50 个方法（快速测试）
python3 run_batch_coverage.py --project Lang --max-methods 50

# 输出：reports/batch/coverage_Lang.csv (包含分子/分母)
```

**CSV 格式**：
```
class_fqcn,method_name,line_cov,instr_cov,branch_cov,line_cov_num,line_cov_den,instr_cov_num,instr_cov_den,branch_cov_num,branch_cov_den
org.apache.commons.lang3.ArrayUtils,add,45.00,50.00,30.00,90,200,100,200,60,200
org.apache.commons.lang3.ArrayUtils,addAll,60.50,65.00,40.00,121,200,130,200,80,200
```

### 3. 并行加速批处理
```bash
# 4 个 worker 并行执行
python3 run_batch_parallel.py --workers 4 --project Lang

# 8 个 worker，限制 100 个方法
python3 run_batch_parallel.py --workers 8 --project Lang --max-methods 100

# 输出：reports/batch/coverage_Lang_worker_*.csv（若启用并行聚合）
```

### 4. 聚合覆盖率统计
```bash
python3 aggregate_coverage.py --project Lang

# 输出：
# ============================================================
# Aggregate coverage for Lang:
# ============================================================
#   line:        51234/100000 (51.23%)
#   instr:       61234/100000 (61.23%)
#   branch:      31234/100000 (31.23%)
# ============================================================
```

## 多项目批处理工作流

### 完整的批量流程（所有项目）
```bash
cd /home/kelvin/work/baseline/randoop/tools

for project in Lang Math Cli Codec Collections CSV Compress JCore JDataBind JXML JxPath JodaTime; do
  echo "===== Processing $project ====="
  
  # 1. 扫描 CC
  python3 scan_complexity.py --project $project --threshold 2
  
  # 2. 并行批处理（8 个 worker）
  python3 run_batch_parallel.py --workers 8 --project $project
  
  # 3. 聚合结果
  python3 aggregate_coverage.py --project $project
  
  echo ""
done
```

**预期耗时**：
- 每个项目 10-30 分钟（取决于方法数和硬件）
- 8 worker 并行：约 5-10 分钟/项目
- 全部 12 项目：1-2 小时

### 批量后台执行（使用 nohup）
```bash
nohup bash -c 'cd /path && python3 run_batch_parallel.py --workers 8 --project Lang' \
  > /tmp/randoop_lang.log 2>&1 &

# 监控日志
tail -f /tmp/randoop_lang.log
```

## 数据处理

### 从 CSV 提取特定信息
```bash
# 查看 Lang 的前 10 行
head -11 /home/kelvin/work/baseline/randoop/reports/batch/coverage_Lang.csv

# 计算平均覆盖率（shell）
awk -F',' 'NR>1 {sum+=$3; count++} END {print "Average line coverage:", sum/count "%"}' \
  /home/kelvin/work/baseline/randoop/reports/batch/coverage_Lang.csv

# 找出覆盖率最高的方法
sort -t',' -k3 -rn /home/kelvin/work/baseline/randoop/reports/batch/coverage_Lang.csv | head -10
```

## 清理工件

### 预览将删除的内容
```bash
python3 clean_artifacts.py --dry-run
```

### 只清理报告和工作区（保留离线资源）
```bash
python3 clean_artifacts.py
```

### 完全清理（包括缓存的 JAR）
```bash
python3 clean_artifacts.py --all-cache
```

## 故障排除

### 检查单个方法的详细日志
```bash
# 查看日志
cat /home/kelvin/work/baseline/randoop/reports/batch/logs/org_apache_commons_lang3_StringUtils_trim.log

# 仅看错误
grep -i "error\|exception\|fail" *.log
```

### 重新运行失败的方法
```bash
# 从日志名提取信息后重新运行
python3 run.py --project Lang --class org.apache.commons.lang3.StringUtils --method trim
```

### 检查 Randoop 是否有可用
```bash
python3 -c "from pathlib import Path; print(Path('../../cache/lib').resolve() / 'randoop-all-4.3.0.jar')" 
# 应该存在该文件
```

## 性能优化

### 对于网络不稳定的环境
1. 首先执行 `prefetch_offline_assets.py`
2. 脚本会自动使用本地缓存（无需网络）

### 对于大项目加速
1. 增加 worker 数量：`--workers 16`（取决于 CPU 核心数）
2. 创建符号链接以避免重复存储：
   ```bash
   ln -s cache/lib/* cache/project_workspace/Lang/lib/
   ```

## 验证结果

### 检查覆盖率 CSV 完整性
```bash
wc -l /home/kelvin/work/baseline/randoop/reports/batch/coverage_Lang.csv
# 应该输出：<method_count + 1> （包括头行）

# 检查数据质量
cut -d',' -f6,7 coverage_Lang.csv | tail -5
# 应该看到有效的数字对
```
