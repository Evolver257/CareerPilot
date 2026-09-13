from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from . import DATASET_VERSION
from .schemas import RAGV2Query

# These are human-written seed questions.  They intentionally describe the
# information need rather than assigning a relevance label to any job.
FOCUS = [
    ("ai-agent", "AI Agent", ["Agent", "智能体"], "哪些岗位需要开发 AI Agent 或智能体"),
    ("rag", "RAG", ["RAG", "向量数据库"], "哪些岗位会做 RAG 检索增强生成"),
    ("backend", "后端", ["Python", "FastAPI"], "哪些岗位主要负责后端服务和接口开发"),
    ("frontend", "前端", ["React", "TypeScript"], "哪些岗位主要做前端页面和交互开发"),
    ("algorithm", "算法", ["机器学习", "PyTorch"], "哪些岗位需要做机器学习算法研发"),
    ("product", "产品", ["需求分析", "产品设计"], "哪些岗位负责产品设计和需求分析"),
    ("test", "测试", ["自动化测试", "Python"], "哪些岗位需要做测试开发或自动化测试"),
    ("data", "数据", ["SQL", "数据分析"], "哪些岗位需要使用 SQL 做数据分析"),
    ("robot", "机器人", ["ROS", "运动控制"], "哪些岗位会做机器人或具身智能"),
    ("nlp", "算法", ["NLP", "自然语言处理"], "哪些岗位和自然语言处理相关"),
    ("cv", "算法", ["计算机视觉", "目标检测"], "哪些岗位需要做计算机视觉或目标检测"),
    ("speech", "算法", ["ASR", "TTS"], "哪些岗位涉及语音识别或语音合成"),
    ("multimodal", "算法", ["多模态", "视觉语言模型"], "哪些岗位需要做多模态模型"),
    ("finetune", "算法", ["LoRA", "SFT"], "哪些岗位会做大模型微调"),
    ("deploy", "算法", ["vLLM", "推理优化"], "哪些岗位需要做模型部署和推理优化"),
    ("java", "后端", ["Java", "Spring"], "哪些岗位使用 Java 和 Spring 开发后端"),
    ("go", "后端", ["Go", "微服务"], "哪些岗位使用 Go 做高并发服务"),
    ("sql", "数据", ["MySQL", "PostgreSQL"], "哪些岗位需要设计数据库并编写 SQL"),
    ("bigdata", "数据", ["Spark", "Flink"], "哪些岗位需要处理大数据或实时数据流"),
    ("cloud", "后端", ["Docker", "Kubernetes"], "哪些岗位需要容器化和云原生部署"),
    ("security", "其他", ["网络安全", "风控"], "哪些岗位与网络安全或业务风控有关"),
    ("embedded", "机器人", ["嵌入式", "STM32"], "哪些岗位需要做嵌入式或单片机开发"),
    ("search", "算法", ["搜索排序", "推荐系统"], "哪些岗位需要做搜索排序或推荐算法"),
    ("knowledge", "RAG", ["知识库", "知识图谱"], "哪些岗位负责知识库或知识图谱建设"),
    ("prompt", "AI Agent", ["Prompt", "提示词"], "哪些岗位需要做 Prompt 设计和大模型应用"),
]

PARAPHRASE = [
    "我想找让模型自己规划步骤并调用工具的工作",
    "我想做先查企业资料再回答问题的应用",
    "我更喜欢写业务接口和服务器端逻辑",
    "我想负责用户在浏览器里看到的页面",
    "我想训练模型并把算法效果做出来",
    "我想把用户问题梳理成产品功能",
    "我想通过自动化脚本找出软件缺陷",
    "我想从业务数据中发现规律帮助决策",
    "我想让机器人感知环境并完成动作",
    "我想让计算机理解人类文字",
    "我想让机器识别图片里的目标",
    "我想做把声音转成文字的算法",
    "我想处理文字和图片一起输入的模型",
    "我想用少量样本调整大模型能力",
    "我想让模型上线后推理更快更省资源",
    "我想用 Java 做企业级服务开发",
    "我想用 Go 写高并发后端服务",
    "我想负责数据表设计和查询性能",
    "我想处理单机放不下的海量数据",
    "我想把程序和运行环境一起交付",
    "我想做防止攻击和异常交易的工作",
    "我想给小型硬件设备编写底层程序",
    "我想让系统给用户推荐更合适的内容",
    "我想把公司文档整理成可以检索的知识库",
    "我想设计指令让大模型稳定完成任务",
]


def _query(
    index: int,
    *,
    query: str,
    query_type: str,
    role: list[str],
    skills: list[str],
    group: str,
    answerability: str = "answerable",
    hard: dict[str, Any] | None = None,
    soft: dict[str, Any] | None = None,
    intent: str = "find_matching_jobs",
) -> dict[str, Any]:
    return RAGV2Query(
        query_id=f"rag-v2-q{index:03d}",
        query=query,
        normalized_intent=intent,
        query_type=query_type,
        target_role=role,
        target_skills=skills,
        hard_constraints=hard or {},
        soft_preferences=soft or {},
        answerability=answerability,
        source="human_written",
        generator_model=None,
        requires_human_review=True,
        template_group=group,
    ).model_dump(mode="json")


def build_query_seed(dataset_version: str = DATASET_VERSION) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    index = 1
    for group, role, skills, literal in FOCUS:
        rows.append(
            _query(
                index, query=literal, query_type="literal", role=[role], skills=skills, group=group
            )
        )
        index += 1
    for group, role, skills, literal in FOCUS:
        rows.append(
            _query(
                index,
                query=f"请帮我筛选：{literal}，优先展示职责写得清楚的岗位",
                query_type="literal",
                role=[role],
                skills=skills,
                group=group,
            )
        )
        index += 1
    for (group, role, skills, _), paraphrase in zip(FOCUS, PARAPHRASE, strict=True):
        rows.append(
            _query(
                index,
                query=paraphrase,
                query_type="paraphrase",
                role=[role],
                skills=skills,
                group=group,
            )
        )
        index += 1
    for (group, role, skills, _), paraphrase in zip(FOCUS, PARAPHRASE, strict=True):
        rows.append(
            _query(
                index,
                query=f"我比较关心这类工作：{paraphrase}",
                query_type="paraphrase",
                role=[role],
                skills=skills,
                group=group,
            )
        )
        index += 1

    multi = [
        (
            "ai-agent",
            "武汉有哪些 1-3 年经验的 AI Agent 后端岗位？",
            ["AI Agent", "后端"],
            ["Python"],
            {"cities": ["武汉"], "experience": "1-3年"},
        ),
        (
            "rag",
            "上海的 RAG 岗位里，有没有全职且要求本科的？",
            ["RAG"],
            ["向量数据库"],
            {"cities": ["上海"], "job_type": ["社招"], "education": "本科"},
        ),
        (
            "backend",
            "深圳有没有 Java 后端校招，最好是互联网公司？",
            ["后端"],
            ["Java", "Spring"],
            {"cities": ["深圳"], "job_type": ["校招"]},
        ),
        (
            "frontend",
            "北京实习前端岗位，最好能用 React 和 TypeScript。",
            ["前端"],
            ["React", "TypeScript"],
            {"cities": ["北京"], "job_type": ["实习"]},
        ),
        (
            "algorithm",
            "想找广州的算法岗位，要求 PyTorch，接受 3 年以上经验。",
            ["算法"],
            ["PyTorch"],
            {"cities": ["广州"], "experience": "3年以上"},
        ),
        (
            "product",
            "上海的 AI 产品经理岗位，最好有需求分析经验。",
            ["产品"],
            ["需求分析"],
            {"cities": ["上海"], "job_type": ["社招"]},
        ),
        (
            "test",
            "成都有没有自动化测试实习，能用 Python 就行？",
            ["测试"],
            ["自动化测试", "Python"],
            {"cities": ["成都"], "job_type": ["实习"]},
        ),
        (
            "data",
            "武汉数据分析岗位，必须会 SQL，本科优先。",
            ["数据"],
            ["SQL"],
            {"cities": ["武汉"], "education": "本科"},
        ),
        (
            "robot",
            "深圳具身智能岗位，想找机器人和 ROS 方向的全职工作。",
            ["机器人"],
            ["ROS"],
            {"cities": ["深圳"], "job_type": ["社招"]},
        ),
        (
            "nlp",
            "北京 NLP 岗位，要求自然语言处理和 Transformer 经验。",
            ["算法"],
            ["NLP", "Transformer"],
            {"cities": ["北京"]},
        ),
        (
            "cv",
            "杭州计算机视觉社招，最好做过目标检测项目。",
            ["算法"],
            ["计算机视觉", "目标检测"],
            {"cities": ["杭州"], "job_type": ["社招"]},
        ),
        (
            "speech",
            "上海语音算法岗位，既做 ASR 又做 TTS 的优先。",
            ["算法"],
            ["ASR", "TTS"],
            {"cities": ["上海"]},
        ),
        (
            "multimodal",
            "武汉多模态算法岗位，硕士，三年以上经验。",
            ["算法"],
            ["多模态"],
            {"cities": ["武汉"], "education": "硕士", "experience": "3年以上"},
        ),
        (
            "finetune",
            "广州大模型微调岗位，要求 LoRA 和 SFT，接受全职。",
            ["算法"],
            ["LoRA", "SFT"],
            {"cities": ["广州"], "job_type": ["社招"]},
        ),
        (
            "deploy",
            "北京做 vLLM 推理优化的岗位，经验不限也可以吗？",
            ["算法"],
            ["vLLM", "推理优化"],
            {"cities": ["北京"], "experience": "不限/应届"},
        ),
    ]
    for repeat in range(2):
        for group, query, roles, skills, hard in multi:
            rows.append(
                _query(
                    index,
                    query=query
                    if not repeat
                    else query.replace("有没有", "请帮我找找有没有").replace("想找", "我想看看"),
                    query_type="multi_constraint",
                    role=roles,
                    skills=skills,
                    group=f"multi-{group}",
                    hard=hard,
                    soft={"company_preference": "互联网"}
                    if group in {"ai-agent", "product"}
                    else {},
                )
            )
            index += 1

    skill_rows = [
        ("Python", "后端", "Python 后端岗位通常还会要求哪些技能？"),
        ("Java", "后端", "Java 服务端职位最常见的任职要求有哪些？"),
        ("React", "前端", "React 前端岗位除了框架本身还看重什么？"),
        ("SQL", "数据", "数据分析岗位对 SQL 的熟练程度有什么要求？"),
        ("RAG", "RAG", "RAG 工程师的 JD 通常会写哪些技能？"),
        ("Agent", "AI Agent", "AI Agent 开发岗位需要掌握哪些工具和框架？"),
        ("PyTorch", "算法", "PyTorch 算法岗通常要求候选人会做到什么程度？"),
        ("Docker", "后端", "容器化岗位会要求哪些 Docker 和 Kubernetes 能力？"),
        ("ROS", "机器人", "机器人算法岗位对 ROS 的要求是什么？"),
        ("自动化测试", "测试", "自动化测试开发需要掌握哪些技术？"),
    ]
    for repeat in range(2):
        for skill, role, query in skill_rows:
            rows.append(
                _query(
                    index,
                    query=query if not repeat else f"如果我会{skill}，相关岗位还会要求哪些能力？",
                    query_type="skill_requirements",
                    role=[role],
                    skills=[skill],
                    group=f"skill-{skill.casefold()}",
                    intent="understand_job_skill_requirements",
                )
            )
            index += 1

    learning = [
        ("RAG", "RAG 工程师", ["Python", "向量数据库"]),
        ("ai-agent", "AI Agent 开发", ["Python", "工具调用"]),
        ("backend", "后端开发", ["Python", "SQL"]),
        ("frontend", "前端开发", ["JavaScript", "React"]),
        ("algorithm", "机器学习算法", ["Python", "PyTorch"]),
        ("product", "AI 产品经理", ["需求分析", "产品设计"]),
        ("test", "测试开发", ["Python", "自动化测试"]),
        ("data", "数据分析", ["SQL", "Excel"]),
        ("robot", "机器人算法", ["C++", "ROS"]),
        ("cloud", "云原生后端", ["Docker", "Kubernetes"]),
    ]
    for repeat in range(2):
        for group, role, skills in learning:
            query = (
                f"想转向{role}，从零开始应该怎样安排学习路线？"
                if not repeat
                else f"如果目标是{role}，先学哪些技能更容易找到工作？"
            )
            rows.append(
                _query(
                    index,
                    query=query,
                    query_type="learning_path",
                    role=[role],
                    skills=skills,
                    group=f"learning-{group}",
                    intent="learn_career_direction",
                )
            )
            index += 1

    comparisons = [
        (("后端", "前端"), ["Python", "React"], "后端开发和前端开发的岗位要求有什么区别？"),
        (
            ("RAG", "AI Agent"),
            ["向量数据库", "工具调用"],
            "RAG 岗位和 AI Agent 岗位，哪个更偏应用工程？",
        ),
        (("算法", "数据"), ["PyTorch", "SQL"], "算法岗和数据分析岗的技能要求怎么比较？"),
        (("产品", "测试"), ["需求分析", "自动化测试"], "产品经理和测试开发的日常工作有什么不同？"),
        (("机器人", "后端"), ["ROS", "微服务"], "机器人软件岗位和互联网后端岗位分别看重什么？"),
    ]
    for repeat in range(2):
        for roles, skills, query in comparisons:
            rows.append(
                _query(
                    index,
                    query=query if not repeat else query.replace("有什么区别", "有哪些不同"),
                    query_type="comparison",
                    role=list(roles),
                    skills=skills,
                    group=f"comparison-{roles[0]}-{roles[1]}",
                    intent="compare_job_families",
                )
            )
            index += 1

    no_answer = [
        "有没有月球基地的 Python 后端开发岗位？",
        "能不能找到恐龙复活项目的机器学习实习？",
        "有没有火星城市的中文产品经理校招？",
        "南极企鹅训练师需要会什么软件工程技能？",
        "有没有木星采矿机器人算法工程师？",
    ]
    for repeat in range(2):
        for query in no_answer:
            rows.append(
                _query(
                    index,
                    query=query if not repeat else f"请帮我确认：{query}",
                    query_type="no_answer",
                    role=[],
                    skills=[],
                    group=f"no-answer-{index}",
                    answerability="unanswerable",
                    intent="verify_no_answer",
                )
            )
            index += 1

    hard_negative = [
        (
            "只提到 React 这个词但实际是 ReAct 推理框架的岗位，我想找真正的 React 前端岗位。",
            ["前端"],
            ["React"],
        ),
        ("JD 里写了需求分析但工作其实是后端开发，我只看产品经理岗位。", ["产品"], ["需求分析"]),
        ("我说的是网络安全，不是生产安全或食品安全岗位，有符合的吗？", ["其他"], ["网络安全"]),
        ("我想找 RAG 检索增强，不是只提到大模型但没有检索工作的职位。", ["RAG"], ["RAG"]),
        ("我想找真正的机器人运动控制，不是制造业安全生产岗位。", ["机器人"], ["运动控制"]),
    ]
    for repeat in range(2):
        for query, roles, skills in hard_negative:
            rows.append(
                _query(
                    index,
                    query=query if not repeat else f"请严格区分：{query}",
                    query_type="hard_negative",
                    role=roles,
                    skills=skills,
                    group=f"hard-negative-{index}",
                    intent="resolve_boundary_intent",
                )
            )
            index += 1

    if len(rows) != 200:
        raise AssertionError(f"RAG V2 seed must contain 200 queries, got {len(rows)}")
    return rows


def write_query_seed(output_path: str | Path) -> list[dict[str, Any]]:
    rows = build_query_seed()
    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "\n".join(json.dumps(row, ensure_ascii=False, sort_keys=True) for row in rows) + "\n",
        encoding="utf-8",
    )
    return rows


def read_queries(path: str | Path) -> list[dict[str, Any]]:
    rows = [
        json.loads(line)
        for line in Path(path).read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    for row in rows:
        RAGV2Query.model_validate(row)
    return rows
