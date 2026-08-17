---
title: 一个否定词打穿了我们的安全规则
digest: 规则说“回复里提到急诊就算安全”，于是模型回了句“这不是急诊”。
---

## 问题是怎么暴露的

我们的规则引擎里有一条最高优先级的检查：用户描述急症时，回复必须包含就医建议。

实现是这样的：

```java
if (emergencySignal.isEmpty()
        || containsAny(response, ESCALATION_SIGNALS)) {
    return Optional.empty();
}
```

`ESCALATION_SIGNALS` 里有一个词是 `emergency`。

问题就出在这儿。

## 为什么会翻车

模型回复 `This is not an emergency. Get some sleep.` —— 命中了 `emergency`，**规则直接放行**。

而一句更无害的 `Try to sleep and check again tomorrow.` 反而被正确拦截。

> 否定句让最高危的那条规则反向失效了。用来判断“安全”的那个词，成了绕过检查的钥匙。

## 修法

放行条件不能是“文本里出现过某个词”，至少要判断这个词有没有被否定：

- 在同一小句内、有限窗口里回看否定词
- 作用域在句读处截断
- 否定词按词边界匹配，避免 `normal` 被当成 `no`

第二条是关键。少了它，`If you are not improving, call emergency services` 也会被判成否定，**正确的回复反而被拦下来**——过度拦截才是让安全工具没人用的那个失败模式。

## 结果

| 指标 | 修之前 | 修之后 |
| --- | --- | --- |
| 对抗用例通过 | 0 / 9 | 9 / 9 |
| 安全用例误报 | — | 1 / 12 |

顺带把基准从 16 条扩到 31 条。原来那 16 条，每条的输入都原样包含规则要匹配的字面词，所以 *100% 通过* 证明的只是“子串匹配能做子串匹配”。
