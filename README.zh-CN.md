# Greenhouse Steward（温室管家）

[English](README.md)

Greenhouse Steward 是一个本地优先的开源项目基础，用于收集温室观测数据，并将数据转化为可解释、需由操作者确认的建议。项目面向小型种植者、教育工作者和创客，核心目标是让使用者掌握自己的数据，并能看懂每条建议的依据。

## 当前状态

`0.1.0` 版本建立了 Python 包、依赖策略、工程检查、架构边界和社区文档。目前源码包仅提供版本元数据；尚不具备采集测量值、提供仪表盘、生成园艺建议或控制设备的能力。

请勿使用这一基础版本操作供暖、通风、灌溉、照明或其他实体系统。所有环境决策均应由具备相应能力的人类操作者负责。

## 预期产品约束

后续实现必须遵守以下原则：

- **本地优先：** 读数、配置和派生建议默认保存在操作者自己的设备上；只有操作者主动启用集成时才可向外发送。
- **输入可追溯：** 每条有效读数都应带有来源、时间戳、单位和校验结果。
- **建议可解释：** 每条建议应说明所依据的读数和规则，不能只给出无法解释的评分。
- **人类保有决定权：** 应用负责展示信息与建议，不得静默驱动温室设备。
- **异常可见：** 对缺失、过期或明显不合理的测量值，应显示数据质量问题，而不是给出看似确定的建议。
- **数据可迁移：** 操作者能够用有文档说明的格式检查并导出自己的测量数据。

预期应用边界包括 MQTT 及明确触发的手工或文件导入、标准化测量数据、本地持久化、规则分析、FastAPI 接口和浏览器仪表盘。每项能力都必须先具备对应测试和文档，才能在项目说明中列为可用功能。

## 环境要求

- Python 3.12
- 强烈建议使用虚拟环境
- 本地 MQTT 代理为可选项，且只有在 MQTT 适配器实现后才有实际用途

所有直接运行时依赖和开发依赖都在 [`pyproject.toml`](pyproject.toml) 中精确锁定版本。更新依赖时应单独审查，不应在安装过程中隐式漂移。

## 开发环境

```bash
python -m venv .venv
python -m pip install --upgrade pip
python -m pip install -e ".[dev]"
```

激活虚拟环境后，可运行单项工程任务：

```bash
python scripts/task.py lint
python scripts/task.py typecheck
python scripts/task.py test
python scripts/task.py audit
python scripts/task.py build
```

PowerShell 用户可以使用同一套任务：

```powershell
.\scripts\task.ps1 lint
```

安装了 `make` 的环境可使用 `make lint`、`make typecheck`、`make test`、`make audit`、`make build` 和 `make quality`。

这些命令定义的是发布门槛，并不代表未经验证的检出版本已经通过检查。任何非零退出状态都应在发布前查明原因。

## 仓库结构

```text
.
├── src/greenhouse_steward/  Python 包
├── scripts/                 跨平台工程任务入口
├── docs/                    架构、安全和发布策略
├── .github/                 贡献流程与依赖管理配置
└── pyproject.toml           包与工具配置
```

## 安全与隐私

温室测量数据可能暴露人员活动规律、位置、作物选择和运营时间。连接真实传感器前，请阅读 [`docs/PRIVACY_AND_SECURITY.md`](docs/PRIVACY_AND_SECURITY.md)。安全问题请按 [`SECURITY.md`](SECURITY.md) 中的流程报告。

## 参与贡献

欢迎提交问题报告、设计讨论、文档改进以及经过认真测试的代码。参与前请阅读 [`CONTRIBUTING.md`](CONTRIBUTING.md) 和 [`CODE_OF_CONDUCT.md`](CODE_OF_CONDUCT.md)。

## 许可证

Greenhouse Steward 采用 [MIT License](LICENSE) 开源。
