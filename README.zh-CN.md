# Greenhouse Steward

[English](README.md) · [MIT](LICENSE) · **当前状态：v0.1.0**

面向园艺爱好者、教学场景和 Maker 的离线优先温室监测工具。它接收规范 CSV 或 MQTT v1 遥测，写入本地 SQLite，并为每条规则命中展示输入值、阈值和建议。

![由内置番茄遥测数据生成的已发布 Pages 演示](docs/images/pages-demo.png)

> 此截图来自使用内置番茄遥测数据生成的已发布 Pages 演示；不含任何用户数据，且不是概念图。

- **可解释：** 作物 profile、异常/掉线、日周趋势和逐条规则证据。
- **本地可携：** 不需要云账号；读数和报告可导出为 CSV 或 JSON。
- **安全默认：** 继电器仅作内存模拟并遵守 profile 时长上限；ESP32 示例默认关闭实体输出。

## 最快开始

```bash
python -m venv .venv
python -m pip install -e ".[dev]"
greenhouse-steward analyze --sample tomato-7d --db greenhouse.sqlite3
greenhouse-steward serve --db greenhouse.sqlite3
```

在浏览器打开 `http://127.0.0.1:8000/dashboard`；服务拒绝非回环地址绑定。

## 真实输入 → 真实输出

```csv
timestamp,temperature_c,humidity_pct,soil_moisture_pct,light_lux
2026-01-05T00:00:00Z,22.4,63.1,48.8,12400
```

```bash
greenhouse-steward analyze --csv readings.csv --device-id bed-a --profile tomato --db greenhouse.sqlite3
greenhouse-steward export bed-a --format json --db greenhouse.sqlite3
```

输出来自已持久化数据，包含状态、规则证据、浇水安全判断、异常和趋势，并非固定 JSON。包内含可复现的 `tomato-7d` 与 `herb-7d` 七天样例。

## 接口与边界

- CLI：`analyze`、`profiles`、`export`、`mqtt validate`、`mqtt ingest`、`relay simulate` 复用同一应用层。
- Web/API：FastAPI 仪表盘、CSRF 表单、JSON API、键盘跳转链接、320px 响应式布局和本地 Plotly 资源。
- MQTT：主题为 `greenhouse/{device_id}/telemetry`；除明确的回环开发例外外要求 TLS。

读数和导出留在本机，密码不会出现在验证错误或报告中。本项目不是水泵、加热、照明或生命安全设备的实体控制器。请阅读[隐私与安全](docs/PRIVACY_AND_SECURITY.md)。

## 验证与文档

```bash
make verify
make demo
make package
make release-check
```

无 `make` 时，依次运行 `python scripts/verify.py`、`python scripts/demo.py`、`python scripts/package_release.py`、`python scripts/release_check.py`。架构、竞品抽样、贡献方式和发布检查分别见 [docs](docs/)。

公开仓库抽样未发现同名且高度同构的活跃项目；本项目明确差异是本地可解释规则工作流与只模拟的安全边界，而非远程设备控制。
