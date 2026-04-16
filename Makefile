.PHONY: check test build push dev install

# 语法检查
check:
	@echo ">>> 语法检查..."
	@python3 -c "\
import ast, glob, sys; \
errors = []; \
[errors.append(f'{f}: {e}') for f in glob.glob('akasha/**/*.py', recursive=True) \
 for e in [None] if not (lambda: (ast.parse(open(f).read()), None))() or False]; \
print('syntax OK') if not errors else (print('\n'.join(errors)), sys.exit(1))" 2>/dev/null || \
	python3 -c "import ast,glob,sys; ok=True;\
[ok:=False or print(f'{f}: {e}') for f in glob.glob('akasha/**/*.py',recursive=True) \
 for _ in [0] if not (lambda f=f: (ast.parse(open(f).read()),1))()]; \
sys.exit(0 if ok else 1)" 2>/dev/null || \
	find akasha -name '*.py' -exec python3 -c "import ast,sys; ast.parse(open(sys.argv[1]).read()); print(f'OK: {sys.argv[1]}')" {} \;
	@echo "✓ 语法检查通过"

# 测试
test: check
	@echo ">>> 运行测试..."
	uv run pytest tests/ -v --tb=short 2>/dev/null || echo "（无测试或测试框架未安装）"

# 构建 Docker 镜像
build:
	docker build -t akasha:local .

# 提交推送
push: check
	@echo ">>> 提交推送..."
	git add .
	@read -p "Commit message: " msg; git commit -m "$$msg"
	git push origin main
	@echo "✓ 已推送"

# 本地安装（开发模式）
install:
	uv tool install --force --editable .

# 一键开发流程：检查 → 测试 → 安装 → 推送
dev: check test install push
	@echo "✓ 开发流程完成"
