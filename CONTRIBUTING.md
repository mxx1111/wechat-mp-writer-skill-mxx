# 参与贡献

感谢你愿意改进公众号发布前体检或排版模版。改动前请先开 Issue 说明问题；小型文档修正可以直接提交 Pull Request。

## 开发与验证

项目运行时只依赖 Python 标准库，支持 Python 3.9 及以上版本。

```bash
python3 -m compileall -q scripts tests
python3 -m unittest discover -s tests -v
python3 scripts/wechat_mp.py doctor
python3 scripts/wechat_mp.py validate-template
```

改动平台限制时，还要运行：

```bash
python3 scripts/check_staleness.py --fail-enforced
```

改动渲染器或模版时，请生成实际 HTML，并在浏览器与公众号后台各检查一次。浏览器预览不能代替真机检查。

## 新增模版

模版目录结构、字段约束和预览生成方法见 [`templates/README.md`](templates/README.md)。[`references/template.schema.json`](references/template.schema.json) 是 `template.json` 字段和样式键的唯一规范来源。

一个模版提交应包含：

- `template.json`
- 能覆盖主要版式的 `sample.md`
- 从真实渲染结果生成并检查过的 `preview.png`
- 对模版说明和回归测试的必要更新

## 敏感信息

不要提交 API 密钥、访问令牌、账号口令、私钥、Cookie、内部地址，或含真实个人信息的公众号草稿与截图。示例数据应匿名化或明确写成虚构示例。

提交前建议在仓库根目录运行：

```bash
gitleaks git . --no-banner --redact
```

CI 会对完整 Git 历史执行同一类扫描，GitHub Secret Scanning Push Protection 也已启用。如果敏感信息已经进入提交，先在对应服务中撤销或轮换凭据；不要把凭据原文粘贴到公开 Issue。

## Pull Request

- 一个 PR 聚焦一个可验证的问题
- 行为变化需要测试，纯重构也要保持现有测试通过
- 不要降低已核实平台规则的强制级别来让测试变绿
- 说明你实际运行过的命令和人工检查
