# new_run.py（精简版 EvoSuite 脚本）

只保留 **EvoSuite 测试生成 + JaCoCo 覆盖率 + 方法级统计** 的核心流程，专注单类/单方法。

## 特点
- 仅针对 `--target-class` 生成测试
- 支持 `--target-method` 或 `--target-method-signature`
- 自动尝试：方法签名 → JVM 描述符 →（可选）无过滤回退（基于 EvoSuite 目标数/测试数）
- 输出 HTML/XML 覆盖率，并打印方法级行/指令/分支覆盖

## 用法示例
```bash
python3 new_run.py \
  --project Lang \
  --time-limit 60 \
  --target-class org.apache.commons.lang3.math.NumberUtils \
  --target-method createNumber
```

### 可选 seed
```bash
python3 new_run.py \
  --project Lang \
  --time-limit 60 \
  --target-class org.apache.commons.lang3.math.NumberUtils \
  --target-method createNumber \
  --seed 42
```

### 测试数过少时自动提高预算
```bash
python3 new_run.py \
  --project Lang \
  --time-limit 60 \
  --target-class org.apache.commons.lang3.math.NumberUtils \
  --target-method createNumber \
  --min-tests 5 \
  --min-tests-retry-mult 3
```

### 目标数过少时触发回退阈值
```bash
python3 new_run.py \
  --project Lang \
  --time-limit 60 \
  --target-class org.apache.commons.lang3.math.NumberUtils \
  --target-method createNumber \
  --min-goals 2 \
  --min-generated-tests 1
```

### 禁用回退（过滤失败直接报错）
```bash
python3 new_run.py \
  --project Lang \
  --time-limit 60 \
  --target-class org.apache.commons.lang3.math.NumberUtils \
  --target-method createNumber \
  --no-fallback
```

### 使用方法签名
```bash
python3 new_run.py \
  --project Lang \
  --time-limit 60 \
  --target-class org.apache.commons.lang3.math.NumberUtils \
  --target-method-signature "public static java.lang.Number createNumber(java.lang.String);"
```

### 仅用方法名过滤（对齐 run_pipeline 行为）
```bash
python3 new_run.py \
  --project Lang \
  --time-limit 60 \
  --target-class org.apache.commons.lang3.math.NumberUtils \
  --target-method createNumber \
  --method-filter-mode name
```

### post-filter 模式（类级生成后过滤，仅保留调用目标方法的测试）
```bash
python3 new_run.py \
  --project Lang \
  --time-limit 60 \
  --target-class org.apache.commons.lang3.math.NumberUtils \
  --target-method createNumber \
  --method-filter-mode post-filter
```

### 自定义覆盖准则（默认不含 WEAKMUTATION）
```bash
python3 new_run.py \
  --project Lang \
  --time-limit 60 \
  --target-class org.apache.commons.lang3.math.NumberUtils \
  --target-method createNumber \
  --evosuite-criteria LINE:BRANCH:EXCEPTION:OUTPUT:METHOD:METHODNOEXCEPTION:CBRANCH
```

## 输出位置
- 测试源码：`project/<Project>_stable/evosuite-tests/`
- 覆盖报告：`project/<Project>_stable/jacoco-report/index.html`

## 说明
- EvoSuite 方法过滤不稳定，脚本默认允许回退生成测试。
- 若你需要完全禁止回退，使用 `--no-fallback`。
- 当方法过滤生成的测试数过少或未调用目标方法时，默认会回退到类级生成，以保证覆盖可用。
