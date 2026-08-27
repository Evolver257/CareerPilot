from __future__ import annotations

import hashlib
import re
import unicodedata
from dataclasses import dataclass

from app.schemas.job_intelligence import (
    JobRequirements,
    JobSalary,
    StructuredJob,
)


@dataclass(frozen=True)
class ParsedJob:
    raw_text: str
    sections: dict[str, list[str]]


@dataclass(frozen=True)
class JobSkillDraft:
    name: str
    skill_type: str
    importance: float
    confidence: float = 0.9


@dataclass(frozen=True)
class JobAnalysis:
    structured_job: StructuredJob
    requirements: JobRequirements
    skills: list[JobSkillDraft]
    content_hash: str


class JobParser:
    """Normalize raw JD text and split common requirement sections."""

    section_aliases = {
        "requirements": {
            "requirements",
            "qualifications",
            "what you bring",
            "任职要求",
            "岗位要求",
            "职位要求",
            "资格要求",
            "任职资格",
            "任职条件",
            "招聘要求",
            "招聘条件",
            "岗位资格",
            "职位资格",
            "我们对你的要求",
            "你需要具备",
        },
        "preferred": {
            "preferred qualifications",
            "nice to have",
            "bonus points",
            "加分项",
            "优先条件",
            "加分条件",
        },
        "responsibilities": {
            "responsibilities",
            "what you will do",
            "what you will work on",
            "you will work on",
            "岗位职责",
            "主要职责",
            "工作职责",
            "工作内容",
            "工作职责与内容",
            "职位职责",
            "你将参与的工作",
            "你将负责的工作",
            "主要工作",
            "你需要参与",
            "预期需求",
            "工作任务",
            "工作内容与职责",
        },
        "summary": {
            "summary",
            "about the role",
            "职位简介",
            "岗位简介",
            "职位描述",
            "岗位描述",
            "岗位定位",
            "岗位简介与职责",
            "实习职位特点",
        },
        "skills": {"skills", "technical skills", "技能要求", "技术栈", "核心技能"},
        "benefits": {
            "benefits",
            "what we offer",
            "你将获得",
            "我们为你提供",
            "福利待遇",
            "岗位福利",
            "实习收获",
            "公司福利",
            "岗位的重要性",
            "岗位价值",
            "为什么加入我们",
            "加入我们",
        },
    }

    def parse(self, raw_jd: str) -> ParsedJob:
        text = self._normalize(raw_jd)
        sections: dict[str, list[str]] = {"body": []}
        current = "body"
        for line in text.splitlines():
            heading, content = self._split_heading(line)
            if heading:
                current = heading
                sections.setdefault(current, [])
                if content:
                    sections[current].append(content)
                continue
            sections.setdefault(current, []).append(line)
        return ParsedJob(raw_text=text, sections=sections)

    @staticmethod
    def _normalize(raw_jd: str) -> str:
        # BOSS pages occasionally expose Kangxi radical glyphs (for example
        # "⼤" and "⽤") instead of normal Chinese characters. NFKC maps
        # those glyphs back to searchable text while leaving the original
        # Chinese punctuation unchanged.
        # Apply compatibility normalization only to the Kangxi-radical block.
        # A full NFKC pass would also turn Chinese full-width punctuation into
        # ASCII punctuation, which makes the persisted JD needlessly differ
        # from what the user saw on the source page.
        normalized = "".join(
            unicodedata.normalize("NFKC", char)
            if 0x2E80 <= ord(char) <= 0x2FFF
            else char
            for char in (raw_jd or "")
        )
        normalized = normalized.replace("\r\n", "\n").replace("\r", "\n")
        normalized = re.sub(r"[\u200b-\u200d\ufeff]", "", normalized)
        lines = [re.sub(r"[ \t\u00a0]+", " ", line).strip() for line in normalized.splitlines()]
        lines = [
            re.sub(r"(?:智联招聘|牛客网)\s*$", "", line).strip()
            for line in lines
        ]
        return "\n".join(line for line in lines if line)

    def _heading_type(self, line: str) -> str | None:
        # BOSS and other job boards frequently return Markdown headings such
        # as "## 你将参与的工作". Strip the Markdown marker first so the
        # semantic heading can still be matched against the aliases below.
        cleaned = re.sub(r"^\s{0,3}#{1,6}\s*", "", line)
        cleaned = cleaned.strip()
        numbered_major_heading = bool(
            re.match(r"^[一二三四五六七八九十百]+\s*[、．.]\s*", cleaned)
        )
        # Long BOSS detail panels commonly number major sections as
        # "一、岗位职责" / "二、岗位要求". Normalize the section marker before
        # matching aliases, while leaving numbered qualification items intact.
        cleaned = re.sub(
            r"^(?:[一二三四五六七八九十百]+|\d{1,2})\s*[、．.]\s*",
            "",
            cleaned,
        )
        cleaned = re.sub(r"^[（(]\s*[一二三四五六七八九十百]+\s*[）)]\s*", "", cleaned)
        cleaned = re.sub(r"^[\s\-—_=~*•·]+|[\s\-—_=~*•·]+$", "", cleaned)
        cleaned = cleaned.strip(" #:：;；【】[]（）()")
        normalized = re.sub(r"\s+", " ", cleaned.casefold())
        for section, aliases in self.section_aliases.items():
            for alias in aliases:
                normalized_alias = re.sub(r"\s+", " ", alias.casefold())
                if normalized == normalized_alias:
                    return section
                # Some BOSS headings contain a qualifier, for example
                # "核心加分项 | AI-Native 开发者". Only accept a prefix when
                # a visible separator follows it so normal prose is not
                # mistaken for a heading.
                remainder = normalized[len(normalized_alias) :]
                if normalized.startswith(normalized_alias) and remainder.startswith(
                    (" ", ":", "：", "|", "｜", "-", "—", "/", "[", "【", "(", "（")
                ):
                    return section
        # Unknown Chinese-numbered top-level sections such as "四、岗位的
        # 重要性" must end the preceding requirements section; otherwise
        # their marketing text is incorrectly classified as qualifications.
        if numbered_major_heading:
            return "body"
        return None

    def _split_heading(self, line: str) -> tuple[str | None, str]:
        bracket = re.match(
            r"^\s*[【\[（(]\s*([^】\]）)]{1,40})\s*[】\]）)]\s*(.*)$",
            line,
        )
        if bracket:
            heading = self._heading_type(bracket.group(1))
            if heading:
                return heading, bracket.group(2).lstrip(" ：:").strip()

        decorated = re.match(r"^\s*[-—_=~]{2,}\s*(.+?)\s*[-—_=~]{2,}\s*(.*)$", line)
        if decorated:
            heading = self._heading_type(decorated.group(1))
            if heading:
                return heading, decorated.group(2).strip()

        heading = self._heading_type(line)
        if heading:
            return heading, ""
        match = re.match(
            r"^[【\[（(]?([^】\]）):：]{2,20})[】\]）)]?[：:]\s*(.+)$",
            line,
        )
        if not match:
            return None, line
        heading = self._heading_type(match.group(1))
        return (heading, match.group(2).strip()) if heading else (None, line)


class SkillExtractor:
    known_skills = (
        "Python",
        "FastAPI",
        "Django",
        "Flask",
        "Java",
        "Spring Boot",
        "MyBatis",
        "Go",
        "Golang",
        "Rust",
        "JavaScript",
        "TypeScript",
        "React",
        "Next.js",
        "Vue",
        "Node.js",
        "HTML",
        "CSS",
        "SQL",
        "PostgreSQL",
        "MySQL",
        "Redis",
        "MongoDB",
        "Docker",
        "Kubernetes",
        "AWS",
        "Azure",
        "GCP",
        "Terraform",
        "Git",
        "Linux",
        "Kafka",
        "RabbitMQ",
        "Spark",
        "Airflow",
        "Machine Learning",
        "Deep Learning",
        "NLP",
        "LLM",
        "RAG",
        "Agent",
        "LangChain",
        "LlamaIndex",
        "Dify",
        "PyTorch",
        "TensorFlow",
        "scikit-learn",
        "Pandas",
        "Figma",
        "Product Management",
        "自动化测试",
        "C",
        "C++",
        "C#",
        "Spring",
        "OpenCV",
        "NumPy",
        "PaddlePaddle",
        "ONNX Runtime",
        "vLLM",
        "Llama.cpp",
        "AOSP",
        "Android",
        "ROS",
        "ROS2",
        "Electron",
        "MCP",
        "Prompt",
        "Function Calling",
        "Tool Use",
        "Cursor",
        "Claude Code",
        "Codex",
        "OpenClaw",
        "AutoGen",
        "Isaac Gym",
        "Isaac Lab",
        "MuJoCo",
        "Genesis",
        "PPO",
        "Actor-Critic",
        "Behavior Cloning",
        "Whole Body Control",
        "Motion Tracking",
        "Motion Retargeting",
        "Sim2Real",
        "SMPL",
        "DeepMimic",
        "Jacobian",
        "Locomotion",
        "IK",
        "QP",
        "GMR",
        "OmniH2O",
        "HOVER",
        "BeyondMimic",
        "Humanoid-Gym",
        "GR00T",
        "ProtoMotions",
        "Unitree",
    )
    skill_aliases = {
        "Spring Boot": ("SpringBoot", "Spring Boot"),
        "MyBatis": ("MyBatis", "MyBatisPlus", "MyBatis-Plus"),
        "Node.js": ("Node.js", "Nodejs"),
        "Next.js": ("Next.js", "Nextjs"),
        "scikit-learn": ("scikit-learn", "sklearn"),
        "LangChain": ("LangChain", "Langchain"),
        "LlamaIndex": ("LlamaIndex", "Llama Index"),
        "C++": ("C++", "C／C++", "C/C++"),
        "C": ("C", "C语言", "C 语言"),
        "OpenCV": ("OpenCV", "opencv"),
        "NumPy": ("NumPy", "Numpy"),
        "ONNX Runtime": ("ONNX Runtime", "ONNXRuntime"),
        "Llama.cpp": ("Llama.cpp", "llama.cpp"),
        "ROS2": ("ROS2", "ROS 2"),
        "MCP": ("MCP", "MCP协议", "MCP 协议"),
        "LLM": ("LLM", "大语言模型", "大模型"),
        "Agent": ("Agent", "智能体", "多智能体"),
        "RAG": ("RAG", "向量检索"),
        "Prompt": ("Prompt", "提示词", "提示工程"),
        "Function Calling": ("Function Calling", "函数调用"),
        "Tool Use": ("Tool Use", "工具调用"),
        "Spring": ("Spring",),
    }

    def extract(self, parsed: ParsedJob) -> list[JobSkillDraft]:
        preferred_text = "\n".join(parsed.sections.get("preferred", []))
        explicit_required_text = "\n".join(
            line
            for section in ("requirements", "skills", "responsibilities")
            for line in parsed.sections.get(section, [])
        )
        # Once a dedicated requirement section exists, do not classify skills
        # mentioned only in the marketing introduction as required.
        required_text = explicit_required_text or "\n".join(parsed.sections.get("body", []))
        drafts: list[JobSkillDraft] = []
        for skill in self.known_skills:
            pattern = self._pattern(skill)
            in_preferred = bool(re.search(pattern, preferred_text, flags=re.IGNORECASE))
            in_required = bool(re.search(pattern, required_text, flags=re.IGNORECASE))
            if not in_preferred and not in_required:
                continue
            skill_type = "preferred" if in_preferred and not in_required else "required"
            importance = 0.7 if skill_type == "required" else 0.4
            drafts.append(JobSkillDraft(skill, skill_type, importance))
        matched_names = {draft.name for draft in drafts}
        # Avoid noisy duplicate tags such as C + C++ and Spring + Spring Boot
        # when the longer technology name already explains the occurrence.
        suppressed = {
            "C" if "C++" in matched_names else "",
            "Spring" if "Spring Boot" in matched_names else "",
        }
        return [draft for draft in drafts if draft.name not in suppressed]

    @staticmethod
    def _bounded_pattern(value: str) -> str:
        if value == "C":
            return r"(?<![A-Za-z0-9+#])C(?![A-Za-z0-9+#])"
        if re.fullmatch(r"[A-Za-z0-9+.# -]+", value):
            return rf"(?<![A-Za-z0-9]){re.escape(value)}(?![A-Za-z0-9])"
        return re.escape(value)

    @classmethod
    def _pattern(cls, skill: str) -> str:
        aliases = cls.skill_aliases.get(skill, (skill,))
        return "(?:" + "|".join(cls._bounded_pattern(value) for value in aliases) + ")"


class RequirementExtractor:
    education_pattern = re.compile(
        r"[^\n]*(?:bachelor|master|phd|degree|本科|硕士|博士|研究生|学士|大专|专科|中专|高中|学历不限|学历不作要求|education)[^\n]*",
        flags=re.IGNORECASE,
    )
    experience_pattern = re.compile(
        r"[^\n]*(?:\d+\s*(?:\+|至|-|~)?\s*(?:years?|年)|经验不限|无经验|无需经验|工作经验|项目经验|相关经验|经验要求|经验|experience)[^\n]*",
        flags=re.IGNORECASE,
    )

    responsibility_prefix = re.compile(
        r"^(?:负责|参与|协助|开发|设计|构建|搭建|维护|完成|推动|跟进|探索|研究|实现|支持|分析|优化|制定|对接|开展|承担|沉淀|整理|收集|执行|进行|帮助|配合|协同|撰写|"
        r"build|develop|design|implement|maintain|support|own|drive|work on)",
        flags=re.IGNORECASE,
    )
    qualification_prefix = re.compile(
        r"^(?:本科|硕士|博士|研究生|大专|专科|学历|经验|熟悉|掌握|了解|具备|有|能够|能|可以|会|精通|熟练|接受|愿意|热爱|对|正在就读|在读|应届|每周|可连续|可长期|英语|专业|工作认真|学习|逻辑|沟通|自驱|实习生)",
        flags=re.IGNORECASE,
    )

    def extract(self, parsed: ParsedJob) -> JobRequirements:
        body_lines = parsed.sections.get("body", [])
        requirement_lines = parsed.sections.get("requirements", [])
        responsibilities = self._items(parsed.sections.get("responsibilities", []))
        description_lines = body_lines + parsed.sections.get("summary", [])
        responsibility_inference_lines = (
            description_lines if not responsibilities else body_lines
        )
        inferred_responsibilities = self._infer_items(
            responsibility_inference_lines, self.responsibility_prefix, allow_numbered=True
        )
        inferred_qualifications = self._infer_items(description_lines, self.qualification_prefix)
        all_lines = self._unique_lines(
            requirement_lines + inferred_qualifications + description_lines
        )
        education = self._first_match(self.education_pattern, all_lines)
        experience = self._first_match(self.experience_pattern, all_lines)
        responsibilities = self._unique_lines(responsibilities + inferred_responsibilities)
        qualifications = self._items(requirement_lines)
        qualifications = self._unique_lines(qualifications + inferred_qualifications)
        preferred = self._items(parsed.sections.get("preferred", []))
        benefits = self._items(parsed.sections.get("benefits", []))
        return JobRequirements(
            education=education,
            experience=experience,
            responsibilities=responsibilities[:12],
            qualifications=qualifications[:16],
            preferred_qualifications=preferred[:12],
            benefits=benefits[:12],
        )

    @staticmethod
    def _unique_lines(lines: list[str]) -> list[str]:
        return list(dict.fromkeys(line for line in lines if line))

    @staticmethod
    def _first_match(pattern: re.Pattern[str], lines: list[str]) -> str:
        for line in lines:
            clean = RequirementExtractor._clean_item(line)
            if pattern.search(clean) and not RequirementExtractor._label_only(clean):
                return clean
        return ""

    @staticmethod
    def _items(lines: list[str]) -> list[str]:
        items: list[str] = []
        for line in lines:
            for part in RequirementExtractor._split_items(line):
                clean = RequirementExtractor._clean_item(part)
                if len(clean) > 4 and not RequirementExtractor._label_only(clean):
                    items.append(clean)
        return list(dict.fromkeys(items))

    @staticmethod
    def _split_items(line: str) -> list[str]:
        # Detail panels sometimes flatten "1、... 2、..." into one text node.
        parts = re.split(
            r"(?<![A-Za-z0-9])(?=\s*(?:\d{1,2}\s*[.)、，,）]|[一二三四五六七八九十]+\s*[、.]))",
            line,
        )
        return [part.strip() for part in parts if part.strip()]

    @staticmethod
    def _clean_item(line: str) -> str:
        return re.sub(
            r"^\s*(?:[-•*·]|\(?\d{1,2}[.)、，,）]|[一二三四五六七八九十]+[、.])\s*",
            "",
            line,
        ).strip(" -—")

    @staticmethod
    def _label_only(line: str) -> bool:
        return bool(re.fullmatch(r"[^。；;，,]{2,24}[：:]", line.strip()))

    @classmethod
    def _infer_items(
        cls,
        lines: list[str],
        prefix: re.Pattern[str],
        *,
        allow_numbered: bool = False,
    ) -> list[str]:
        candidates: list[str] = []
        for line in lines:
            clean = cls._clean_item(line)
            if len(clean) <= 4 or cls._label_only(clean):
                continue
            numbered = bool(
                re.match(r"^\s*(?:\d{1,2}\s*[.)、，,）]|[一二三四五六七八九十]+\s*[、.])", line)
            )
            if prefix.search(clean) or (allow_numbered and numbered):
                candidates.append(clean)
        return list(dict.fromkeys(candidates))


class JobNormalizer:
    def __init__(
        self,
        parser: JobParser | None = None,
        skill_extractor: SkillExtractor | None = None,
        requirement_extractor: RequirementExtractor | None = None,
    ) -> None:
        self.parser = parser or JobParser()
        self.skill_extractor = skill_extractor or SkillExtractor()
        self.requirement_extractor = requirement_extractor or RequirementExtractor()

    def analyze(self, raw_jd: str, *, title_hint: str | None = None) -> JobAnalysis:
        parsed = self.parser.parse(raw_jd)
        requirements = self.requirement_extractor.extract(parsed)
        skills = self.skill_extractor.extract(parsed)
        title = title_hint or self._title(parsed)
        summary = self._summary(parsed, title=title)
        benefits = requirements.benefits
        profile = StructuredJob(
            title=title,
            role_category=self._role_category(title, parsed.raw_text),
            level=self._level(title, parsed.raw_text),
            job_type=self._job_type(parsed.raw_text),
            location=self._location(parsed.raw_text),
            salary=self._salary(parsed.raw_text),
            required_skills=[skill.name for skill in skills if skill.skill_type == "required"],
            preferred_skills=[skill.name for skill in skills if skill.skill_type == "preferred"],
            education_requirement=requirements.education,
            experience_requirement=requirements.experience,
            responsibilities=requirements.responsibilities,
            benefits=benefits,
            keywords=self._keywords(title, skills),
            summary=summary,
        )
        return JobAnalysis(
            structured_job=profile,
            requirements=requirements,
            skills=skills,
            content_hash=hashlib.sha256(parsed.raw_text.encode("utf-8")).hexdigest(),
        )

    @staticmethod
    def _title(parsed: ParsedJob) -> str:
        for line in parsed.raw_text.splitlines():
            if (
                len(line) <= 160
                and not JobNormalizer._metadata_line(line)
                and JobParser()._heading_type(line) is None
            ):
                return line.lstrip("# ")
        return "Untitled Job"

    @staticmethod
    def _metadata_line(line: str) -> bool:
        return bool(
            re.match(
                r"^(?:company|location|salary|公司|地点|薪资|城市|经验|学历|岗位|职位|类型)[：:]",
                line.strip(),
                flags=re.IGNORECASE,
            )
        )

    @staticmethod
    def _role_category(title: str, text: str) -> str:
        haystack = f"{title} {text}".casefold()
        title_text = title.casefold()
        if "full-stack" in title_text or "full stack" in title_text or "全栈" in title_text:
            return "Full-stack Engineering"
        if any(keyword in title_text for keyword in ("backend", "后端", "platform", "api")):
            return "Backend Engineering"
        if any(keyword in title_text for keyword in ("frontend", "前端")):
            return "Frontend Engineering"
        if any(keyword in title_text for keyword in ("product", "产品")):
            return "Product"
        if any(keyword in title_text for keyword in ("design", "设计", "ux", "ui")):
            return "Design"
        if any(
            keyword in title_text
            for keyword in (
                "algorithm",
                "算法",
                "machine learning",
                "机器学习",
                "大模型",
                "agent",
                "ai",
            )
        ):
            return "Machine Learning"
        categories = (
            (("backend", "后端", "api"), "Backend Engineering"),
            (("frontend", "前端", "react", "vue"), "Frontend Engineering"),
            (("data", "数据", "spark", "airflow"), "Data Engineering"),
            (("machine learning", "ml engineer", "算法", "机器学习"), "Machine Learning"),
            (("devops", "sre", "platform", "云"), "DevOps / Platform"),
            (("product", "产品"), "Product"),
            (("design", "设计", "ux", "ui"), "Design"),
            (("qa", "quality", "测试", "test automation"), "Quality Engineering"),
            (("mobile", "ios", "android"), "Mobile Engineering"),
            (("security", "安全"), "Security"),
        )
        for keywords, category in categories:
            if any(keyword in haystack for keyword in keywords):
                return category
        return "General"

    @staticmethod
    def _level(title: str, text: str) -> str:
        haystack = f"{title} {text}".casefold()
        for keywords, level in (
            (("intern", "实习"), "Intern"),
            (("junior", "初级"), "Junior"),
            (("senior", "高级"), "Senior"),
            (("lead", "负责人"), "Lead"),
            (("manager", "经理"), "Manager"),
        ):
            if any(keyword in haystack for keyword in keywords):
                return level
        return "Mid-level"

    @staticmethod
    def _job_type(text: str) -> str:
        haystack = text.casefold()
        if "intern" in haystack or "实习" in haystack:
            return "Internship"
        if "contract" in haystack or "合同" in haystack:
            return "Contract"
        if "part-time" in haystack or "兼职" in haystack:
            return "Part-time"
        if "full-time" in haystack or "全职" in haystack:
            return "Full-time"
        return "Full-time"

    @staticmethod
    def _location(text: str) -> str:
        labeled = re.search(
            r"(?:location|地点|工作地点|工作地|城市)\s*[:：]\s*([^\n]+)",
            text,
            flags=re.IGNORECASE,
        )
        if labeled:
            return labeled.group(1).strip()
        for location in (
            "Remote",
            "Shanghai",
            "Beijing",
            "Shenzhen",
            "Hangzhou",
            "Guangzhou",
            "New York",
            "武汉",
            "成都",
            "南京",
            "西安",
            "苏州",
            "重庆",
            "天津",
            "合肥",
            "长沙",
            "厦门",
            "北京",
            "上海",
            "深圳",
            "杭州",
            "广州",
            "远程",
            "线上",
        ):
            if location.casefold() in text.casefold() or location in text:
                return location
        return ""

    @staticmethod
    def _salary(text: str) -> JobSalary:
        range_pattern = (
            r"(?P<currency>[$¥￥])?\s*"
            r"(?P<minimum>\d{1,3}(?:\.\d+)?)\s*(?P<minimum_unit>[kK千萬万])?\s*"
            r"[-–~至到]\s*"
            r"(?P<maximum>\d{1,3}(?:\.\d+)?)\s*(?P<maximum_unit>[kK千萬万])?"
        )
        labeled = re.search(
            rf"(?:薪资|salary|月薪|日薪|时薪|compensation)\s*[:：]?[^\n\d$¥￥]{{0,10}}{range_pattern}",
            text,
            flags=re.IGNORECASE,
        )
        generic = re.search(
            rf"{range_pattern}\s*(?:元(?:/月|/天|/小时)?|块|/月|/天|/小时|薪|USD|CNY)",
            text,
            flags=re.IGNORECASE,
        )
        match = labeled or generic
        if not match:
            return JobSalary()

        def to_int(value: str) -> int:
            return int(round(float(value)))

        minimum = to_int(match.group("minimum"))
        maximum = to_int(match.group("maximum"))
        return JobSalary(
            minimum=minimum,
            maximum=maximum,
            currency="USD" if "$" in match.group(0) or "USD" in match.group(0).upper() else "CNY",
        )

    @staticmethod
    def _summary(parsed: ParsedJob, *, title: str = "") -> str:
        summary_lines = parsed.sections.get("summary", [])
        if summary_lines:
            candidates = JobNormalizer._summary_lines(summary_lines)
        else:
            candidates = JobNormalizer._summary_lines(parsed.sections.get("body", []))
        return " ".join(line for line in candidates if line != title)[:600]

    @staticmethod
    def _summary_lines(lines: list[str]) -> list[str]:
        metadata = re.compile(
            r"^(?:company|location|salary|公司|地点|薪资|城市|经验|学历|工作地点|工作地|岗位|职位|类型)[：:]",
            re.IGNORECASE,
        )
        return [
            re.sub(r"^\s*[-•*·]\s*", "", line).strip()
            for line in lines
            if len(line.strip()) > 4
            and not metadata.match(line.strip())
            and not re.fullmatch(r"[-—_=~]{2,}", line.strip())
        ]

    @staticmethod
    def _keywords(title: str, skills: list[JobSkillDraft]) -> list[str]:
        values = [title, *[skill.name for skill in skills]]
        return list(dict.fromkeys(value for value in values if value))[:20]
