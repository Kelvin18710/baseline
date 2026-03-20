# 1) 扫描复杂度（默认阈值 2，输出到 data/complexity）
python3 /home/kelvin/work/baseline/evosuite/tools/scan_complexity.py --project Lang

# 2) 批量跑（默认 EvoSuite 时间设置，自动用 data/complexity 下 cc>=2 的方法）
python3 /home/kelvin/work/baseline/evosuite/tools/run_batch_coverage.py --project Lang
python3 /data/peiting/symbolic/baseline/evosuite/tools/run_batch_coverage.py --project Lang

# 3) 并行批量跑（8 workers）
python3 /home/kelvin/work/baseline/evosuite/tools/run_batch_parallel.py --workers 8 --project Lang