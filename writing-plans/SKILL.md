---
name: writing-plans
description: Use when you have a spec or requirements for a multi-step task, before touching code
---

# 编写实施计划

## 总览

编写完整、可执行的实施计划。默认假设执行者熟悉编程，但不了解当前代码库、工具链和业务背景。计划必须把“要改哪些文件、每个文件职责、测试怎么写、命令怎么跑、预期结果是什么、如何验收”写清楚。

**语言要求：所有计划文档默认使用中文。** 代码、命令、文件路径、函数名、错误信息、提交信息可以保持英文；正文标题、解释、任务说明、步骤说明、验收标准、交付提示必须使用中文。

**开头必须声明：**“我正在使用 writing-plans skill 来创建实施计划。”

**上下文：** 最好在独立 worktree 中执行；如果用户已有指定工作区，以用户指定为准。

**保存位置：** `docs/superpowers/plans/YYYY-MM-DD-<feature-name>.md`
- 用户指定其他位置时，以用户要求为准。

## 范围检查

如果需求覆盖多个独立子系统，应建议拆成多个计划，每个计划都能独立交付、独立测试。不要把互相独立的数据库迁移、前端重构、模型评估、部署流水线强塞进一个不可执行的大计划。

## 文件结构

定义任务前，先列出将创建或修改的文件，并说明每个文件负责什么。

- 文件职责要清晰，接口要明确。
- 优先设计小而专注的文件，避免把多个职责塞进一个大文件。
- 相关文件放在一起；按职责拆分，不按抽象层硬拆。
- 现有代码库有固定风格时，跟随现有模式。
- 如果必须改一个已经过大的文件，可以在计划中明确拆分边界。

文件结构决定任务拆分。每个任务都应该是可独立理解、可独立测试、可独立验收的小块。

## 任务粒度

每个步骤只做一个动作，通常 2-5 分钟能完成：

- 写一个失败测试。
- 运行测试确认失败。
- 写最小实现让测试通过。
- 运行测试确认通过。
- 提交或记录检查点。

## 计划文档头部

每份计划必须用下面的中文头部格式开头：

```markdown
# [功能名称]实施计划

> **给 agentic worker 的要求：** 必须使用子技能 `superpowers:subagent-driven-development`（推荐）或 `superpowers:executing-plans`，按任务逐项执行本计划。所有步骤使用复选框（`- [ ]`）跟踪状态。

**目标：** [一句话说明要构建什么]

**架构：** [2-3 句话说明方案和关键边界]

**技术栈：** [关键技术、库、服务和运行时]

---
```

## 任务结构

````markdown
### 任务 N：[组件名称]

**涉及文件：**
- 新建：`exact/path/to/file.py`
- 修改：`exact/path/to/existing.py:123`
- 测试：`tests/exact/path/to/test.py`

- [ ] **步骤 1：编写失败测试**

```python
def test_specific_behavior():
    result = function(input)
    assert result == expected
```

- [ ] **步骤 2：运行测试确认失败**

运行：`pytest tests/path/test.py::test_name -v`

预期：失败，错误包含 `function not defined`

- [ ] **步骤 3：编写最小实现**

```python
def function(input):
    return expected
```

- [ ] **步骤 4：运行测试确认通过**

运行：`pytest tests/path/test.py::test_name -v`

预期：通过

- [ ] **步骤 5：提交或记录检查点**

```bash
git add tests/path/test.py src/path/file.py
git commit -m "feat: add specific feature"
```
````

## 禁止占位

计划中不能出现下面这些失败写法：

- `TBD`、`TODO`、`implement later`、`fill in details`
- “添加适当错误处理”“处理边界情况”“写相关测试”但不给出具体代码或断言
- “类似任务 N”而不重复必要内容
- 只描述要做什么，却不给实际代码片段、命令和预期结果
- 后面任务引用前面没有定义的函数、类型、字段或命令

如果步骤修改代码，必须给出足够具体的代码块。代码可以是可粘贴的完整片段，也可以是明确替换哪个函数/代码块的完整内容。

## 必须记住

- 文件路径必须精确。
- 计划正文必须中文。
- 命令、代码、路径、API 名称可以保持原文。
- 每个测试步骤都要写运行命令和预期输出。
- 每个实现步骤都要写清楚具体改法。
- 遵循 DRY、YAGNI、TDD。
- 频繁提交；如果当前目录不是 git 仓库，写明“记录无 git 检查点”的预期。

## 自查

写完计划后，必须从读者角度检查一次，并在文档末尾保留简短自查结论。

**1. 需求覆盖：** 每个需求是否都能对应到具体任务？有缺口就补任务。

**2. 占位符扫描：** 搜索 `TBD`、`TODO`、`类似`、`适当`、`后续实现` 等词，发现就改成具体步骤。

**3. 类型一致性：** 后面任务使用的函数名、字段名、类型名是否与前面定义一致。

## 交付提示

保存计划后，用中文向用户给出两个执行选项：

```markdown
计划已完成并保存到 `docs/superpowers/plans/<filename>.md`。有两个执行方式：

1. **Subagent-Driven（推荐）** - 每个任务派发一个新 subagent，任务之间进行 review，迭代更快
2. **Inline Execution** - 在当前会话中按 executing-plans 执行，分批检查

你希望使用哪种方式？
```

如果用户选择 Subagent-Driven，后续必须使用 `superpowers:subagent-driven-development`。

如果用户选择 Inline Execution，后续必须使用 `superpowers:executing-plans`。
