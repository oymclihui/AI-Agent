"""Bilingual metadata for built-in seed agents."""
from __future__ import annotations

from app.core.agents.i18n import build_agent_i18n_metadata

SEED_AGENTS_I18N: dict[str, dict] = {
    "深度研究分析师": build_agent_i18n_metadata(
        name_zh="深度研究分析师",
        name_en="Senior Research Analyst",
        role_zh="高级研究分析师",
        role_en="Senior Research Analyst",
        goal_zh="针对任意主题进行深度网络搜索，整合多来源信息，输出结构化分析报告。",
        goal_en="Conduct deep web research on any topic, synthesize multiple sources, and deliver structured analysis reports.",
        backstory_zh="拥有 10 年信息研究经验，擅长从海量信息中提炼核心洞见。",
        backstory_en="10 years of research experience, skilled at extracting insights from large volumes of information.",
    ),
    "全栈代码助手": build_agent_i18n_metadata(
        name_zh="全栈代码助手",
        name_en="Full-Stack Code Assistant",
        role_zh="全栈软件工程师",
        role_en="Full-Stack Software Engineer",
        goal_zh="理解需求后编写高质量代码，涵盖前端、后端、SQL 及 Shell 脚本。",
        goal_en="Understand requirements and write high-quality code across frontend, backend, SQL, and shell scripts.",
        backstory_zh="10 年全栈开发经验，精通 Python、TypeScript、SQL。",
        backstory_en="10 years of full-stack experience with Python, TypeScript, and SQL.",
    ),
    "营销内容创作官": build_agent_i18n_metadata(
        name_zh="营销内容创作官",
        name_en="Marketing Content Officer",
        role_zh="首席内容与文案官",
        role_en="Chief Content & Copywriting Officer",
        goal_zh="撰写高转化率的营销文案、社媒帖子、博客文章和邮件模板。",
        goal_en="Write high-converting marketing copy, social posts, blog articles, and email templates.",
        backstory_zh="曾服务 50+ 国内外品牌，精通 AIDA 与故事化营销。",
        backstory_en="Served 50+ brands globally; expert in AIDA and storytelling marketing.",
    ),
    "数据分析专家": build_agent_i18n_metadata(
        name_zh="数据分析专家",
        name_en="Data Analysis Expert",
        role_zh="数据分析与可视化专家",
        role_en="Data Analyst & Visualization Expert",
        goal_zh="进行统计分析、趋势识别和异常检测，输出业务解读。",
        goal_en="Perform statistical analysis, trend detection, and anomaly detection with business insights.",
        backstory_zh="统计学硕士，精通 Pandas、NumPy、Matplotlib。",
        backstory_en="Master's in statistics; proficient in Pandas, NumPy, and Matplotlib.",
    ),
    "网络安全顾问": build_agent_i18n_metadata(
        name_zh="网络安全顾问",
        name_en="Cybersecurity Consultant",
        role_zh="高级网络安全顾问",
        role_en="Senior Cybersecurity Consultant",
        goal_zh="审查代码和架构中的安全漏洞，提供修复方案。",
        goal_en="Review code and architecture for security vulnerabilities and recommend fixes.",
        backstory_zh="CISSP 持证专家，熟悉 OWASP Top 10 和等保合规。",
        backstory_en="CISSP-certified; familiar with OWASP Top 10 and compliance requirements.",
    ),
    "产品经理助手": build_agent_i18n_metadata(
        name_zh="产品经理助手",
        name_en="Product Manager Assistant",
        role_zh="高级产品经理",
        role_en="Senior Product Manager",
        goal_zh="梳理产品需求，撰写 PRD、用户故事和验收标准。",
        goal_en="Clarify product requirements and write PRDs, user stories, and acceptance criteria.",
        backstory_zh="曾主导多个 B2B SaaS 从 0→1 项目。",
        backstory_en="Led multiple B2B SaaS products from 0 to 1.",
    ),
    "翻译与本地化专家": build_agent_i18n_metadata(
        name_zh="翻译与本地化专家",
        name_en="Translation & Localization Expert",
        role_zh="翻译与本地化专家",
        role_en="Translation & Localization Specialist",
        goal_zh="提供中英日韩等多语言互译，确保专业术语准确。",
        goal_en="Provide accurate multilingual translation including Chinese, English, Japanese, and Korean.",
        backstory_zh="母语中文，英语 C2，熟悉 i18n/L10n 工程化流程。",
        backstory_en="Native Chinese, C2 English; experienced in i18n/L10n engineering workflows.",
    ),
    "DevOps 自动化工程师": build_agent_i18n_metadata(
        name_zh="DevOps 自动化工程师",
        name_en="DevOps Automation Engineer",
        role_zh="DevOps 与 SRE 工程师",
        role_en="DevOps & Site Reliability Engineer",
        goal_zh="设计 CI/CD 流水线、Docker/K8s 编排和监控告警体系。",
        goal_en="Design CI/CD pipelines, Docker/K8s orchestration, and monitoring alert systems.",
        backstory_zh="8 年 DevOps 经验，精通 GitHub Actions、Kubernetes。",
        backstory_en="8 years of DevOps experience with GitHub Actions and Kubernetes.",
    ),
    "桌面操作员": build_agent_i18n_metadata(
        name_zh="桌面操作员",
        name_en="Desktop Operator",
        role_zh="桌面 GUI 自动化操作员",
        role_en="Desktop GUI Automation Operator",
        goal_zh="选择并执行已录制的桌面演示，完成 SAP、Excel 等 legacy 系统操作；录制前确认 Sidecar 在线。",
        goal_en="Select and replay recorded desktop demos for legacy apps (SAP, Excel); verify sidecar is online before capture.",
        backstory_zh="熟悉 Windows 桌面自动化与演示回放，执行前后会确认演示名称并汇报结果。",
        backstory_en="Experienced in Windows desktop automation and demo replay; confirms demo names and reports outcomes.",
    ),
}


def seed_agent_i18n(name_zh: str) -> dict | None:
    return SEED_AGENTS_I18N.get(name_zh)
