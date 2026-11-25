# 实验进度报告

`experiment-progress-report` 是一个 Codex 技能。给它实验目录和要总结的周期，它会从运行记录、配置、评估表和图像中核对基线与改进结果，写出中文阶段报告，并为组会整理可回查的证据。

## 安装

在 PowerShell 中将仓库克隆到 Codex 的个人技能目录。

```powershell
git clone https://github.com/hwxyk2004/Exp-conclusion-skill.git "$HOME/.codex/skills/experiment-progress-report"
```

## 使用

把下面的示例路径和汇报周期替换为自己的实验材料。

> 用 `$experiment-progress-report` 总结 `D:\实验\本轮对照` 最近两周的进展。请对比改进方法和基线，说明哪些结论有数据支持、哪些还缺对照，并给出下一轮最值得做的实验。

同一输出目录中会生成两个文件。

| 文件 | 用途 |
| --- | --- |
| `实验进度报告.pdf` | 摘要交代本轮最重要的进展，正文说明方法、对照条件、结果与下一步。关键结论可按证据编号回查原始记录。 |
| `组会素材索引.md` | 按候选结论列出图表、数据位置和待讨论的问题。需要准备组会时，可把索引交给[组会汇报备稿](https://github.com/hwxyk2004/Pre-skill)生成逐页提纲。 |

随附的 [PDF 渲染脚本](scripts/render_report.py)使用 Python、ReportLab 和可嵌入的中文字体。手动调用时，报告 JSON 的格式与字体参数见 [PDF 输入与渲染说明](references/pdf-input.md)。
