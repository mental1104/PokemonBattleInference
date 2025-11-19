# PokemonBattleInference

一个用于宝可梦对战推演与伤害计算的 FastAPI 服务。

## 项目结构

```
PokemonBattleInference/
├── data/raw/config/         # 初始化数据库所需的 CSV 数据
├── pokemon_battle_inference/
│   ├── api/                 # FastAPI 的 schema 和 router
│   ├── core/                # 日志、配置等核心设施
│   ├── domain/              # 领域模型与能力、伤害计算逻辑
│   ├── infrastructure/      # 数据库连接与 SQLAlchemy 模型
│   ├── services/            # 构建宝可梦实体的服务
│   └── static/              # 自带的 Swagger 资源
├── scripts/                 # 数据导入脚本（依赖 data/raw）
├── tests/                   # Pytest 用例
├── requirements.txt
└── run.sh
```

## 开发与运行

1. 安装依赖：
   ```bash
   pip install -r requirements.txt
   ```
2. 设置 `PYTHONPATH` 方便直接导入包（本地与容器均可）：
   ```bash
   export PYTHONPATH=$PYTHONPATH:/data/PokemonBattleInference
   ```
3. 本地启动 FastAPI 服务：
   ```bash
   uvicorn pokemon_battle_inference.main:app --reload
   ```
4. 或者使用 Docker：
   ```bash
   docker build -t pokemon-calculator .
   docker run -d -p 8000:8000 pokemon-calculator
   # 或使用 docker-compose
   docker-compose up -d
   ```

## 数据与脚本

- `scripts/` 目录包含数据导入脚本，读取 `data/raw/config` 中的 CSV。
- 执行脚本前请确保数据库环境变量已设置（`PGUSER/PGPASSWORD/PGHOST/...`）并运行：
  ```bash
  python scripts/init_database.py
  ```

## 测试

```bash
pytest tests
```
