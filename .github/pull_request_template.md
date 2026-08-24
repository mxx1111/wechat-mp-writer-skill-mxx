## 改了什么

<!-- 说明用户可观察到的变化，以及为什么需要它。 -->

## 怎么验证

<!-- 列出实际运行的命令；模版改动请补充浏览器和公众号后台检查结果。 -->

- [ ] `python3 -m unittest discover -s tests -v`
- [ ] `python3 scripts/wechat_mp.py doctor`
- [ ] `python3 scripts/wechat_mp.py validate-template`

## 提交前检查

- [ ] 行为变化有对应测试，或已说明不需要测试的原因
- [ ] 没有提交 API 密钥、令牌、口令、私钥、Cookie、内部地址或真实个人信息
- [ ] 示例稿件与截图已经匿名化
- [ ] 文档和预览已随行为变化同步更新
