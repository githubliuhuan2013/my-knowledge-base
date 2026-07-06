# 个人知识库

基于 GitHub + Markdown + AI 的个人知识管理系统。

## 快速开始

```bash
# 创建新笔记
kb new "笔记标题" --tags 标签1,标签2

# 导入 Word 文档
kb import ~/Desktop/资料.docx

# 列出笔记
kb list --tag 标签1

# 搜索笔记
kb search "关键词"

# 同步到 GitHub（跨设备）
kb sync
```

## 目录结构

```
knowledge-base/
├── notes/           # 知识笔记（Markdown）
├── _originals/      # 原始 Word 文档
├── _templates/      # 笔记模板
├── _tools/          # 工具脚本
└── _index/          # 搜索索引
```
