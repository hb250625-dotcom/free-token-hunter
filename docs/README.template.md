<!--
  可复用项目 README 模板
  用法：复制本文件为你的项目 README.md，替换所有 {{...}} 占位符即可。
  徽章取自 shields.io（静态）与 GitHub 动态徽章，按需增删。
-->

<p align="center">
  <img src="https://img.shields.io/badge/license-{{LICENSE}}-blue?style=flat-square" alt="license" />
  <img src="https://img.shields.io/badge/{{LANG}}-powered-3776AB?logo={{LANG_LOGO}}&logoColor=white" alt="language" />
  <img src="https://img.shields.io/github/last-commit/{{OWNER}}/{{REPO}}?style=flat-square" alt="last commit" />
  <img src="https://github.com/{{OWNER}}/{{REPO}}/actions/workflows/ci.yml/badge.svg" alt="ci" />
</p>

<h1 align="center">{{PROJECT_NAME}}</h1>

<p align="center">
  <b>{{ONE_LINE_TAGLINE}}</b><br />
  <i>{{SUBTITLE}}</i>
</p>

---

{{PROJECT_DESCRIPTION}}

> {{MOTIVATION_OR_NOTE}}

## 目录

- [特性](#特性)
- [目录结构](#目录结构)
- [快速开始](#快速开始)
- [使用说明](#使用说明)
- [配置](#配置)
- [贡献指南](#贡献指南)
- [许可证](#许可证)

---

## 特性

- ✨ {{FEATURE_1}}
- 🚀 {{FEATURE_2}}
- 🛡️ {{FEATURE_3}}
- 📦 {{FEATURE_4}}

---

## 目录结构

```
{{PROJECT_NAME}}/
├── {{ENTRY_FILE}}          # 主程序 / 入口
├── {{SRC_DIR}}/             # 源码目录
├── {{DOCS_DIR}}/            # 文档
├── {{TEST_DIR}}/            # 测试
├── .gitignore
├── LICENSE
└── README.md
```

---

## 快速开始

```bash
# 1. 克隆
git clone https://github.com/{{OWNER}}/{{REPO}}.git
cd {{REPO}}

# 2. 安装（按需替换）
{{INSTALL_COMMANDS}}

# 3. 运行
{{RUN_COMMANDS}}
```

> **环境要求**：{{PREREQUISITES}}

---

## 使用说明

{{USAGE_DETAILS}}

```bash
{{USAGE_EXAMPLE}}
```

---

## 配置

| 配置项 | 说明 | 默认值 |
|--------|------|--------|
| `{{CONFIG_KEY_1}}` | {{DESC_1}} | `{{DEFAULT_1}}` |
| `{{CONFIG_KEY_2}}` | {{DESC_2}} | `{{DEFAULT_2}}` |

---

## 贡献指南

欢迎通过 Issue / PR 参与。提交前请确认：

1. **问题描述清晰**：Issue 附复现步骤；PR 说明动机与改动范围。
2. **本地可构建**：`{{BUILD_OR_TEST_COMMAND}}` 通过。
3. **风格一致**：遵循现有代码规范，提交信息语义化（`feat/fix/docs/...`）。
4. **不提交密钥**：敏感信息放 `.env`（已被 `.gitignore` 排除），勿强制添加。
5. **分支约定**：功能用 `feat/xxx`，修复用 `fix/xxx`，PR 目标 `main`。

---

## 许可证

本项目以 [{{LICENSE}} 许可证](./LICENSE) 开源。
