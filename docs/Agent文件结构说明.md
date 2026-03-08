# Agent 文件结构说明

本文档说明 Manobot 中 Agent 相关文件的存储位置和修改方法。

---

## 目录结构概览

```
~/.nanobot/                           # Nanobot 数据目录
├── config.json                       # 📝 主配置文件
├── workspace/                        # 默认 Agent 的工作区
│   ├── memory/
│   │   ├── MEMORY.md                 # 长期记忆文件
│   │   └── HISTORY.md                # 历史记录
│   └── skills/                       # 技能脚本目录
└── history/
    └── cli_history                   # CLI 命令历史

~/.manobot/                           # Manobot 多智能体数据目录
├── agents/
│   ├── {agent_id}/                   # 每个 Agent 的隔离目录
│   │   ├── workspace/                # Agent 专属工作区
│   │   │   ├── memory/
│   │   │   │   ├── MEMORY.md
│   │   │   │   └── HISTORY.md
│   │   │   └── skills/
│   │   ├── memory/                   # Agent 内存存储
│   │   └── sessions/                 # Agent 会话存储
│   │       └── {session_key}.json    # 会话文件
│   ├── coder/
│   │   ├── workspace/
│   │   ├── memory/
│   │   └── sessions/
│   └── assistant/
│       ├── workspace/
│       ├── memory/
│       └── sessions/
└── history/                          # 系统历史文件
```

---

## 文件详解

### 1. 主配置文件

**位置**: `~/.nanobot/config.json`

**功能**: 存储所有 Agent 定义、通道配置、提供商密钥等。

**修改方式**:
```bash
# 方式 1: 使用 CLI 命令（推荐）
manobot agents add coder --name "代码助手"
manobot agents bind coder --channel telegram

# 方式 2: 直接编辑文件
vim ~/.nanobot/config.json
```

**结构示例**:
```json
{
  "agents": {
    "defaults": {
      "workspace": "~/.nanobot/workspace",
      "model": "anthropic/claude-sonnet-4-20250514",
      "provider": "auto",
      "maxTokens": 8192,
      "temperature": 0.1
    },
    "list": [
      {
        "id": "assistant",
        "default": true,
        "name": "默认助手"
      },
      {
        "id": "coder",
        "name": "代码助手",
        "workspace": "~/projects",
        "model": "deepseek/deepseek-coder"
      }
    ],
    "bindings": [...]
  },
  "channels": {...},
  "providers": {...}
}
```

---

### 2. Agent 数据目录

**位置**: `~/.manobot/agents/{agent_id}/`

**结构**:
| 子目录 | 说明 |
|--------|------|
| `workspace/` | Agent 的工作区（存放文件、代码等） |
| `memory/` | Agent 的内存存储 |
| `sessions/` | Agent 的会话存储 |
| `skills/` | Agent 专属技能（可选） |

**注意**: 
- 默认 Agent 使用 `~/.nanobot/workspace/`
- 非默认 Agent 使用隔离的 `~/.manobot/agents/{id}/workspace/`

---

### 3. 工作区文件 (workspace)

**位置**: 
- 默认 Agent: `~/.nanobot/workspace/`
- 其他 Agent: `~/.manobot/agents/{agent_id}/workspace/`

**可配置**: 支持在 config.json 中自定义路径

```json
{
  "id": "coder",
  "workspace": "~/my-projects"  // 自定义工作区
}
```

**子目录**:
| 路径 | 说明 | 可修改 |
|------|------|--------|
| `memory/MEMORY.md` | 长期记忆，Agent 可读写 | ✅ 可手动编辑 |
| `memory/HISTORY.md` | 对话历史摘要 | ✅ 可手动编辑 |
| `skills/` | 自定义技能脚本 | ✅ 可添加 .md 文件 |

**修改 MEMORY.md**:
```markdown
# Agent 记忆

## 用户偏好
- 用户喜欢简洁的回复
- 代码风格偏好 PEP8

## 项目信息
- 当前项目: manobot
- 技术栈: Python + TypeScript
```

---

### 4. 会话文件 (sessions)

**位置**: `~/.manobot/agents/{agent_id}/sessions/`

**文件格式**: `{session_key}.json`

**内容**: 存储对话历史、上下文状态等

```json
{
  "messages": [
    {"role": "user", "content": "你好"},
    {"role": "assistant", "content": "你好！有什么可以帮助你的？"}
  ],
  "metadata": {
    "created_at": "2024-01-01T00:00:00",
    "updated_at": "2024-01-01T00:01:00"
  }
}
```

**清理会话**: 
```bash
# 删除特定 Agent 的所有会话
rm -rf ~/.manobot/agents/coder/sessions/*

# 删除特定会话文件
rm ~/.manobot/agents/coder/sessions/telegram_123456.json
```

---

### 5. 技能文件 (skills)

**位置**: 
- 内置技能: `agent/skills/` (项目目录)
- Agent 专属技能: `~/.manobot/agents/{agent_id}/workspace/skills/`

**格式**: Markdown 文件 (`.md`)

**创建自定义技能**:
```bash
# 在 Agent 工作区创建技能
cat > ~/.manobot/agents/coder/workspace/skills/my-skill/SKILL.md << 'EOF'
# My Custom Skill

## 触发条件
当用户提到 "运行我的脚本" 时激活

## 操作步骤
1. 检查脚本文件存在
2. 执行脚本
3. 返回结果
EOF
```

---

## 路径优先级

Agent 配置支持自定义路径覆盖，优先级如下：

### workspace 解析
1. `AgentEntryConfig.workspace` (如果设置)
2. 默认 Agent → `~/.nanobot/workspace`
3. 非默认 Agent → `~/.manobot/agents/{id}/workspace`

### agent_dir 解析
1. `AgentEntryConfig.agent_dir` (如果设置)
2. 默认 → `~/.manobot/agents/{id}/`

### sessions_dir 解析
1. `AgentEntryConfig.sessions_dir` (如果设置)
2. 默认 → `{agent_dir}/sessions/`

### memory_dir 解析
1. `AgentEntryConfig.memory_dir` (如果设置)
2. 默认 → `{agent_dir}/memory/`

---

## 自定义路径配置

在 `config.json` 中可以为每个 Agent 指定自定义路径：

```json
{
  "agents": {
    "list": [
      {
        "id": "coder",
        "name": "代码助手",
        "workspace": "~/projects",           // 自定义工作区
        "agentDir": "~/data/coder",          // 自定义数据根目录
        "sessionsDir": "~/data/coder/sess",  // 自定义会话目录
        "memoryDir": "~/data/coder/mem"      // 自定义内存目录
      }
    ]
  }
}
```

**说明**: 
- 路径支持 `~` 表示用户主目录
- 修改后需重启网关生效

---

## 常用操作

### 查看 Agent 路径信息

```bash
manobot agents show <agent_id>
```

输出示例：
```
Agent: coder
  Name:       代码助手
  Model:      deepseek/deepseek-coder
  Provider:   auto
  Default:    No

Paths:
  Workspace:  /home/user/projects
  Memory:     /home/user/.manobot/agents/coder/memory
  Sessions:   /home/user/.manobot/agents/coder/sessions
```

### 备份 Agent 数据

```bash
# 备份特定 Agent
tar -czvf coder-backup.tar.gz ~/.manobot/agents/coder/

# 备份所有 Agent
tar -czvf all-agents-backup.tar.gz ~/.manobot/agents/
```

### 迁移 Agent 数据

```bash
# 1. 停止网关
# 2. 复制数据
cp -r ~/.manobot/agents/old-agent ~/.manobot/agents/new-agent

# 3. 修改 config.json 中的 agent id
# 4. 重启网关
manobot gateway
```

### 重置 Agent 状态

```bash
# 清除会话（保留记忆）
rm -rf ~/.manobot/agents/coder/sessions/*

# 清除记忆（保留会话）
rm -rf ~/.manobot/agents/coder/memory/*

# 完全重置（删除所有数据）
rm -rf ~/.manobot/agents/coder/
```

---

## 文件权限说明

| 文件/目录 | 建议权限 | 说明 |
|-----------|----------|------|
| `config.json` | 600 | 包含 API 密钥，仅所有者可读写 |
| `sessions/` | 700 | 会话数据目录 |
| `memory/` | 700 | 内存数据目录 |
| `workspace/` | 755 | 工作区目录 |

```bash
# 设置安全权限
chmod 600 ~/.nanobot/config.json
chmod -R 700 ~/.manobot/agents/*/sessions
chmod -R 700 ~/.manobot/agents/*/memory
```

---

## 注意事项

1. **修改配置后需重启网关** - CLI 命令或直接编辑 config.json 后，需运行 `manobot gateway` 重启

2. **Agent ID 会被规范化** - ID 会转为小写，非字母数字字符替换为连字符

3. **默认 Agent 共享工作区** - 默认 Agent 使用 `~/.nanobot/workspace`，其他 Agent 隔离

4. **会话文件自动创建** - 首次与 Agent 对话时自动创建会话文件

5. **技能文件热加载** - 部分技能修改可能需要重启网关才能生效
