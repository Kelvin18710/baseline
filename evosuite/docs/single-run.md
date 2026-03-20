# run.py（单方法运行）

`tools/run.py` 负责单类/单方法的 EvoSuite 生成与 JaCoCo 覆盖统计。

## 特点

- 支持 `--target-class` + `--target-method` / `--target-method-signature`
- 支持方法过滤失败回退（可关闭）
- 输出 HTML/XML 覆盖率与方法级统计

## 基本命令

```bash
python3 tools/run.py \
  --project Lang \
  --time-limit 60 \
  --target-class org.apache.commons.lang3.math.NumberUtils \
  --target-method createNumber
```

## 常用选项

- 指定随机种子：`--seed 42`
- 禁用回退：`--no-fallback`
- 方法过滤模式：`--method-filter-mode signature|name|post-filter`
- 提高测试数重试预算：`--min-tests` + `--min-tests-retry-mult`

## 输出位置

- 工作目录：`cache/project_workspace/<Project>_stable/`
- 测试源码：`cache/project_workspace/<Project>_stable/evosuite-tests/`
- 覆盖报告：`cache/project_workspace/<Project>_stable/jacoco-report/index.html`
