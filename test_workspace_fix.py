"""测试 workspace 隔离修复"""
from mano.agents.scope import resolve_agent_workspace, resolve_agent_config, resolve_default_agent_id
from agent.config.schema import Config, AgentDefaults, AgentEntryConfig, AgentsConfig
from pathlib import Path

# 模拟配置
defaults = AgentDefaults(workspace='~/.manobot/workspace', model='claude')

# 两个 agent: 一个 default，一个非 default
agent_list = [
    AgentEntryConfig(id='nanobot', default=True, name='Nanobot'),
    AgentEntryConfig(id='coder', default=False, name='Coder'),  # 没有 workspace
    AgentEntryConfig(id='writer', default=False, name='Writer', workspace='~/writing'),  # 有显式 workspace
]

agents_config = AgentsConfig(defaults=defaults, agent_list=agent_list)
config = Config(agents=agents_config)

print('=== 测试 resolve_agent_workspace ===')
print(f'Default agent ID: {resolve_default_agent_id(config)}')
print()

# Test each agent
for agent_id in ['nanobot', 'coder', 'writer']:
    ws = resolve_agent_workspace(config, agent_id)
    agent_cfg = resolve_agent_config(config, agent_id)
    print(f'{agent_id}:')
    print(f'  workspace: {ws}')
    print(f'  config.workspace: {agent_cfg.get("workspace")}')
    print()

print('=== 验证隔离性 ===')
nanobot_ws = resolve_agent_workspace(config, 'nanobot')
coder_ws = resolve_agent_workspace(config, 'coder')
writer_ws = resolve_agent_workspace(config, 'writer')

print(f'nanobot 和 coder workspace 不同: {nanobot_ws != coder_ws}')
print(f'coder 和 writer workspace 不同: {coder_ws != writer_ws}')
print(f'nanobot 使用 defaults.workspace: {str(nanobot_ws) == str(Path("~/.manobot/workspace").expanduser())}')

# 测试切换 default agent 后的情况
print()
print('=== 测试切换 default agent 后的情况 ===')
agent_list2 = [
    AgentEntryConfig(id='nanobot', default=False, name='Nanobot'),  # 现在非 default
    AgentEntryConfig(id='coder', default=True, name='Coder'),  # 现在是 default，但没有 workspace
]
agents_config2 = AgentsConfig(defaults=defaults, agent_list=agent_list2)
config2 = Config(agents=agents_config2)

print(f'新的 Default agent ID: {resolve_default_agent_id(config2)}')
print()

for agent_id in ['nanobot', 'coder']:
    ws = resolve_agent_workspace(config2, agent_id)
    agent_cfg = resolve_agent_config(config2, agent_id)
    print(f'{agent_id}:')
    print(f'  workspace: {ws}')
    print(f'  config.workspace: {agent_cfg.get("workspace")}')
    print()

nanobot_ws2 = resolve_agent_workspace(config2, 'nanobot')
coder_ws2 = resolve_agent_workspace(config2, 'coder')
print(f'coder (新 default) 使用 defaults.workspace: {str(coder_ws2) == str(Path("~/.manobot/workspace").expanduser())}')
print(f'nanobot (非 default) 使用隔离 workspace: {str(nanobot_ws2) == str(Path.home() / ".manobot" / "agents" / "nanobot" / "workspace")}')
