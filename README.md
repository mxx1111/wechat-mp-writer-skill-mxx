# wechat-mp-writer-skill-mxx

微信公众号文章全流程写作助手 - OpenClaw Skill

[![GitHub stars](https://img.shields.io/github/stars/mxx1111/wechat-mp-writer-skill-mxx?style=flat-square)](https://github.com/mxx1111/wechat-mp-writer-skill-mxx/stargazers)
[![License: MIT](https://img.shields.io/badge/license-MIT-blue.svg?style=flat-square)](LICENSE)

## 功能介绍

这是一个专为微信公众号运营者设计的 OpenClaw 技能，提供从选题到发布的一站式文章创作辅助。

### 核心功能

1. **热点选题建议** - 根据领域/关键词搜索最新热点，提供选题角度
2. **文章撰写** - 支持技术干货、故事叙事、观点评论等多种风格
3. **AI 去味润色** - 去除 AI 写作痕迹，让文章读起来像真人写的
4. **配图建议** - 推荐配图类型，提供封面图设计建议
5. **一键发布** - 生成符合微信格式的 Markdown，可发布到公众号草稿箱

## 安装方法

### 方法一：通过 ClawHub 安装（推荐）

```bash
openclaw skill install github:mxx1111/wechat-mp-writer-skill-mxx
```

### 方法二：手动安装

1. 克隆仓库到本地
```bash
cd ~/.openclaw/skills
git clone https://github.com/mxx1111/wechat-mp-writer-skill-mxx.git wechat-mp-writer
```

2. 重启 OpenClaw 或重新加载技能

## 使用方法

安装完成后，在 OpenClaw 中直接告诉助手你想写什么类型的公众号文章即可。

示例：
- "帮我写一篇关于微服务架构的技术文章"
- "给我一些 Java 领域的热点选题建议"
- "润色一下我这段草稿，让它读起来更自然"

## 文件结构

```
wechat-mp-writer-skill-mxx/
├── SKILL.md                      # 主技能文件
├── references/
│   ├── image-guide.md           # 公众号配图指南
│   └── humanize-guide.md        # AI 去味润色指南
├── README.md                     # 本文件
└── LICENSE                       # 开源协议
```

## 依赖

- OpenClaw >= 1.0
- 可选：wechat-mp-publisher skill（用于一键发布到公众号）

## 开源协议

MIT License - 详见 [LICENSE](LICENSE) 文件

## 作者

穆雄雄（GitHub: [@mxx1111](https://github.com/mxx1111)）

- 博客：https://blog.csdn.net/qq_34137397
- 公众号：雄雄的小课堂

## 更新日志

### v1.0.0 (2026-02-21)
- 初始版本发布
- 支持热点选题、文章撰写、AI 去味润色、配图建议功能
