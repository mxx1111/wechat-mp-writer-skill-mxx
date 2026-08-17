# 模版

## 为什么模版不能是 CSS 文件

公众号编辑器会剥掉 `<style>` 标签和所有 `class` 属性，**只保留元素上的 `style="..."` 内联声明**。所以外链 CSS、`<style>` 块、class 选择器在公众号里一律无效。

模版因此不是样式表，而是一份「每种元素长什么样」的声明，由 [`../scripts/apply_template.py`](../scripts/apply_template.py) 在生成 HTML 时逐个标签编译进去。

## 现有模版

| id | 名称 | 适合 |
| --- | --- | --- |
| [`policy-whitepaper`](policy-whitepaper/) | 政策解读·白皮书 | 政策解读、调研报告、医保社保、机关单位汇报 |
| [`tech-deepdive`](tech-deepdive/) | 技术干货 | 技术教程、源码分析、架构设计、踩坑记录 |

## 用法

```bash
python3 scripts/apply_template.py --list
python3 scripts/apply_template.py article.md -t policy-whitepaper -o out.html
```

在浏览器里打开 `out.html`，全选复制，粘进公众号编辑器。

加 `--standalone` 会额外套一层模拟公众号宽度（677px）的白色卡片，方便在浏览器里预览效果。**这一层只用于预览，不要复制**，粘贴时用不带 `--standalone` 的版本。

## 加一个新模版

建一个目录，放三个文件：

```
templates/你的模版id/
  template.json    必需
  sample.md        建议，用来生成预览图
  preview.png      建议，README 里展示
```

`template.json` 的结构：

```json
{
  "id": "your-template",
  "name": "显示名",
  "description": "一句话说清它适合什么、不适合什么",
  "bestFor": ["题材一", "题材二"],
  "palette": { "paper": "#FFFFFF", "ink": "#1F2328", "accent": "#1F6FEB" },
  "notes": ["设计上做过的取舍，以及为什么"],
  "styles": {
    "body": "background:#FFFFFF;color:#1F2328;...",
    "h2": "...",
    "p": "..."
  }
}
```

`styles` 的每个键对应一种元素，值是 CSS 声明串（不带选择器和花括号）。支持的键：

```
body
h2  h3  h4
p  strong  em
code_inline  code_block  code_block_text
blockquote  blockquote_text
ul  ol  li
table  tr  th  td
hr
img  figure  figcaption
link  link_url
```

缺哪个键就不给那种元素加样式，元素本身照常输出——模版写漏一项，内容不该跟着消失。

## 做模版时的注意

**别用 H1。** 文章标题在公众号后台单独填，正文里的 `#` 会被引擎降级成 H2。

**链接会被渲染成不可点的文字。** 公众号正文里的外链本来就点不了，引擎会把 `[文字](url)` 渲染成强调文字加一个灰色的地址，免得读者以为能点。`link` 和 `link_url` 两个键控制这两部分的样式。

**代码块要控制字号和行距。** 公众号正文宽度固定，代码稍大就横向滚动。13px、行距 1.6 是比较稳的组合。

**别依赖冷门字体。** iOS 和安卓的中文字体差异很大，宋体在多数安卓机上会退化。要保证退化之后仍然可读，不要靠字体撑设计。

**深色背景块慎用大面积。** 部分客户端的深色模式会二次处理背景色，大块背景容易糊成一片。窄的竖线、边框比背景块稳。

**对比度过 WCAG AA。** 正文和背景至少 4.5:1。把配色和对比度写进 `notes`，别人改的时候知道边界在哪。

## 生成预览图

```bash
python3 scripts/apply_template.py templates/你的模版id/sample.md \
  -t 你的模版id --standalone -o /tmp/preview.html

"/Applications/Google Chrome.app/Contents/MacOS/Google Chrome" \
  --headless --disable-gpu --hide-scrollbars --force-device-scale-factor=2 \
  --window-size=725,1500 --screenshot=templates/你的模版id/preview.png \
  "file:///tmp/preview.html"
```

`--window-size` 的高度按内容调，不要留大片空白。

> 浏览器预览和公众号里的实际效果**存在差异**。字体回退、行距处理、深色模式都可能不一样。正式用之前，请在公众号后台真的粘一次，用手机看一遍。
