"""Predeclared query families; splits are by topic, never by paraphrase.

Regex labels are silver candidates, NOT independently human-verified gold.
The benchmark exports supporting spans for review and accepts reviewed labels.
"""

TOPICS = [
    (
        "rag",
        r"\bRAG\b|检索增强",
        "哪些岗位需要 RAG 检索增强生成",
        "我想做让模型先查资料再回答的工作",
    ),
    (
        "agent",
        r"\bAgent\b|智能体",
        "哪些岗位开发 Agent 智能体",
        "有没有让模型自主规划步骤并调用工具的岗位",
    ),
    (
        "vector",
        r"向量数据库|Milvus|FAISS|pgvector|向量检索",
        "向量数据库与向量检索的岗位要求",
        "哪些工作要把资料转成向量后寻找语义相近内容",
    ),
    (
        "finetune",
        r"LoRA|微调|SFT",
        "模型微调 LoRA SFT 相关岗位",
        "希望做用少量领域样本调整模型参数的工作",
    ),
    (
        "eval",
        r"模型评测|模型评估|评测集|评估体系",
        "模型评测与评测集构建岗位",
        "哪些工作需要验证生成答案的质量与可靠性",
    ),
    (
        "deploy",
        r"模型部署|推理优化|vLLM|TensorRT",
        "模型部署与推理优化岗位",
        "我想做让模型服务上线后更快响应的工作",
    ),
    ("python", r"\bPython\b", "要求 Python 的职位", "哪些岗位使用派森语言编程"),
    ("java", r"\bJava\b|Spring", "Java Spring 后端岗位", "我想做基于爪哇语言的企业服务开发"),
    (
        "frontend",
        r"前端|React|Vue",
        "前端 React Vue 开发岗位",
        "想做用户在浏览器里看到和操作的界面",
    ),
    (
        "backend",
        r"后端|服务端|FastAPI",
        "后端服务开发岗位",
        "哪些岗位主要负责业务接口和服务器端逻辑",
    ),
    (
        "sql",
        r"SQL|MySQL|PostgreSQL",
        "SQL 关系型数据库岗位",
        "哪些职位需要设计数据表并编写查询语句",
    ),
    ("redis", r"Redis|缓存", "Redis 缓存相关岗位", "哪些职位需要避免反复读取数据库来加快响应"),
    (
        "docker",
        r"Docker|容器化|Kubernetes|K8s",
        "Docker 容器化部署岗位",
        "有没有把程序和运行环境打包交付的工作",
    ),
    ("linux", r"Linux", "Linux 系统技能要求", "哪些工作需要熟悉企鹅操作系统的命令行"),
    (
        "nlp",
        r"自然语言处理|\bNLP\b|文本分类",
        "自然语言处理 NLP 岗位",
        "希望做让计算机理解人类文字含义的工作",
    ),
    (
        "cv",
        r"计算机视觉|图像识别|目标检测|图像算法",
        "计算机视觉 图像算法岗位",
        "想让机器识别照片中的物体并理解画面",
    ),
    (
        "speech",
        r"语音|ASR|TTS",
        "语音识别与语音合成岗位",
        "哪些工作涉及把说话声音转成文字或者反过来",
    ),
    ("multi", r"多模态", "多模态模型岗位", "希望处理文字图片声音联合理解的任务"),
    (
        "robot",
        r"机器人|具身",
        "机器人与具身智能岗位",
        "想把智能算法用在能感知环境并执行动作的机器上",
    ),
    (
        "control",
        r"控制算法|运动控制|轨迹规划|路径规划",
        "运动控制与轨迹规划岗位",
        "让机器平稳运动并规划如何到达目的地的工作",
    ),
    (
        "recommend",
        r"推荐算法|推荐系统|搜索排序",
        "推荐系统与搜索排序岗位",
        "想做为用户挑选更感兴趣内容的算法",
    ),
    (
        "data",
        r"数据分析|数据挖掘",
        "数据分析与数据挖掘岗位",
        "想通过分析业务数字发现规律并辅助决策",
    ),
    (
        "bigdata",
        r"大数据|Spark|Flink|Hadoop",
        "大数据 Spark Flink 岗位",
        "哪些工作需要处理单台机器装不下的数据",
    ),
    (
        "test",
        r"测试开发|自动化测试|软件测试",
        "软件测试与测试开发岗位",
        "我想通过编写自动检查程序找出软件缺陷",
    ),
    ("cpp", r"C\+\+", "C++ 开发岗位", "哪些工作需要使用西加加语言实现高性能程序"),
    ("pytorch", r"PyTorch", "PyTorch 深度学习岗位", "想用火炬深度学习框架训练神经网络"),
    (
        "transformer",
        r"Transformer|注意力机制",
        "Transformer 注意力机制相关岗位",
        "哪些岗位需要理解模型如何关注序列中重要的信息",
    ),
    (
        "prompt",
        r"Prompt|提示词",
        "Prompt 提示词工程岗位",
        "通过设计输入指令引导模型稳定完成任务的工作",
    ),
    (
        "tool",
        r"Function.?Call|Tool.?Call|工具调用|MCP",
        "工具调用 Function Calling MCP 岗位",
        "让模型连接外部程序执行查询和操作的岗位",
    ),
    (
        "langchain",
        r"LangChain|LangGraph",
        "LangChain LangGraph 应用岗位",
        "用链式编排框架组合语言模型和工具的职位",
    ),
    (
        "etl",
        r"数据清洗|数据标注|ETL",
        "数据清洗标注岗位",
        "希望做把杂乱原始材料整理成可训练数据的工作",
    ),
    ("security", r"安全|风控", "安全与风险控制相关岗位", "有没有识别异常行为并降低系统风险的工作"),
    (
        "embedded",
        r"嵌入式|单片机|STM32",
        "嵌入式单片机岗位",
        "想在资源受限的小型硬件设备上开发程序",
    ),
    (
        "product",
        r"产品经理|产品设计|需求分析",
        "产品设计与需求分析岗位",
        "想研究用户问题并把它变成软件功能需求",
    ),
    ("intern", r"实习", "提供实习机会的岗位", "我还在读书希望先进入企业实践的工作机会"),
    (
        "knowledge",
        r"知识库|知识图谱",
        "知识库与知识图谱岗位",
        "想做把企业资料组织起来便于查找和关联的系统",
    ),
]
NEGATIVES = [
    "火星载人基地生命维持岗位",
    "古埃及象形文字石碑修复师",
    "南极企鹅潜水教练",
    "中世纪城堡攻城器械操作员",
    "深海热泉考古摄影师",
    "月球矿场重力校准师",
    "恐龙基因复活实验主管",
    "木星大气采矿飞行员",
]


def cases():
    result = []
    for index, (topic, criterion, literal, semantic) in enumerate(TOPICS):
        for variant, query in [("literal", literal), ("paraphrase", semantic)]:
            result.append(
                {
                    "id": f"{topic}-{variant}",
                    "topic": topic,
                    "query": query,
                    "criterion": criterion,
                    "split": "dev" if index % 3 == 0 else "test",
                    "variant": variant,
                    "label_status": "silver_requires_review",
                }
            )
    for index, query in enumerate(NEGATIVES):
        result.append(
            {
                "id": f"absent-{index}",
                "topic": f"absent-{index}",
                "query": query,
                "criterion": query,
                "split": "test",
                "variant": "unanswerable",
                "label_status": "silver_requires_review",
            }
        )
    return result
