"use client";

import { useEffect, useState, type FormEvent } from "react";

import {
  deleteResume,
  getResumeChunks,
  getResumes,
  parseResume,
  updateResume,
  uploadResume,
  type Resume,
  type ResumeChunk,
  type ResumeProfile,
} from "../../lib/api";

function maskPersonalInfo(value: string): string {
  return value
    .replace(/(?<!\d)(1\d{2})\d{4}(\d{4})(?!\d)/g, "$1****$2")
    .replace(/([\w.+-]{2})[\w.+-]*(@[\w.-]+\.[A-Za-z]{2,})/g, "$1***$2");
}

const supportedFiles = ".pdf,.docx,.txt,.md,.markdown";

function formatDate(value: string) {
  return new Date(value).toLocaleString("zh-CN", { dateStyle: "medium" });
}

function formatDateRange(start?: string | null, end?: string | null) {
  return [start, end].filter(Boolean).join(" — ");
}

function ProfileList({ profile }: { profile: ResumeProfile }) {
  return (
    <div className="space-y-6">
      <div>
        <p className="text-sm font-medium text-slate-500">简历摘要</p>
        <p className="mt-2 whitespace-pre-wrap leading-7 text-slate-700">{maskPersonalInfo(profile.summary) || "暂无摘要"}</p>
      </div>

      <div>
        <p className="text-sm font-medium text-slate-500">核心技能</p>
        <div className="mt-3 flex flex-wrap gap-2">
          {profile.skills.length > 0 ? profile.skills.map((skill) => (
            <span key={skill} className="rounded-full bg-indigo-50 px-3 py-1 text-sm font-medium text-indigo-700">
              {skill}
            </span>
          )) : <span className="text-sm text-slate-400">暂无识别到的技能</span>}
        </div>
      </div>

      <div className="grid gap-4 md:grid-cols-2">
        <ProfileGroup title="工作与实习" count={profile.experience.length}>
          {profile.experience.map((item, index) => (
            <div key={`${item.company}-${item.role}-${index}`} className="rounded-xl bg-slate-50 p-4">
              <p className="font-semibold text-slate-800">{item.role || "未命名职位"}</p>
              <p className="mt-1 text-sm text-slate-500">{item.company || "未填写公司"}</p>
              {item.bullets.length > 0 && <p className="mt-3 whitespace-pre-wrap text-sm leading-6 text-slate-600">{item.bullets.join("\n")}</p>}
            </div>
          ))}
        </ProfileGroup>

        <ProfileGroup title="项目经历" count={profile.projects.length}>
          {profile.projects.map((item, index) => (
            <div key={`${item.name}-${index}`} className="rounded-xl bg-slate-50 p-4">
              <p className="font-semibold text-slate-800">{item.name || "未命名项目"}</p>
              {item.technologies.length > 0 && <p className="mt-2 text-xs font-medium text-indigo-600">{item.technologies.join(" · ")}</p>}
              {item.description && item.description.trim() !== item.name.trim() && (
                <details className="group mt-3">
                  <summary className="cursor-pointer text-sm font-medium text-slate-500 transition group-open:text-indigo-700">查看项目详情</summary>
                  <p className="mt-2 whitespace-pre-wrap text-sm leading-6 text-slate-600">{item.description}</p>
                </details>
              )}
            </div>
          ))}
        </ProfileGroup>

        <ProfileGroup title="教育经历" count={profile.education.length}>
          {profile.education.map((item, index) => (
            <div key={`${item.institution}-${index}`} className="rounded-xl bg-slate-50 p-4">
              <p className="font-semibold text-slate-800">{item.institution || "未填写院校"}</p>
              <p className="mt-1 text-sm text-slate-500">{[item.degree, item.field].filter(Boolean).join(" · ") || "未填写专业"}</p>
              {formatDateRange(item.start_date, item.end_date) && <p className="mt-1 text-xs text-slate-400">{formatDateRange(item.start_date, item.end_date)}</p>}
              {item.details.length > 0 && <p className="mt-2 whitespace-pre-wrap text-sm leading-6 text-slate-600">{item.details.join("\n")}</p>}
            </div>
          ))}
        </ProfileGroup>

        <ProfileGroup title="荣誉与论文" count={profile.awards.length + profile.publications.length}>
          {[...profile.awards.map((item) => item.name), ...profile.publications.map((item) => item.title)].map((item, index) => (
            <p key={`${item}-${index}`} className="rounded-xl bg-slate-50 p-4 text-sm text-slate-700">{item}</p>
          ))}
        </ProfileGroup>
      </div>
    </div>
  );
}

function ProfileGroup({ title, count, children }: { title: string; count: number; children: React.ReactNode }) {
  return (
    <div>
      <div className="flex items-center justify-between">
        <p className="text-sm font-medium text-slate-500">{title}</p>
        <span className="text-xs text-slate-400">{count}</span>
      </div>
      <div className="mt-3 space-y-2">{count > 0 ? children : <p className="rounded-xl bg-slate-50 p-4 text-sm text-slate-400">暂无内容</p>}</div>
    </div>
  );
}

function ChunkList({ chunks }: { chunks: ResumeChunk[] }) {
  return (
    <div className="space-y-3">
      {chunks.map((chunk, index) => (
        <article key={chunk.id} className="rounded-xl border border-slate-200 bg-slate-50 p-4">
          <div className="flex flex-wrap items-center justify-between gap-2">
            <p className="font-medium text-slate-800">{index + 1}. {chunk.chunk_type}</p>
            <span className="text-xs text-slate-500">向量维度 · {chunk.embedding_dimensions}</span>
          </div>
          <p className="mt-3 whitespace-pre-wrap text-sm leading-6 text-slate-600">{chunk.content}</p>
        </article>
      ))}
      {chunks.length === 0 && <p className="text-sm text-slate-400">暂无语义分块。</p>}
    </div>
  );
}

export default function ResumePage() {
  const [resumes, setResumes] = useState<Resume[]>([]);
  const [selected, setSelected] = useState<Resume | null>(null);
  const [chunks, setChunks] = useState<ResumeChunk[]>([]);
  const [file, setFile] = useState<File | null>(null);
  const [name, setName] = useState("");
  const [loading, setLoading] = useState(true);
  const [uploading, setUploading] = useState(false);
  const [parsing, setParsing] = useState(false);
  const [saving, setSaving] = useState(false);
  const [editing, setEditing] = useState(false);
  const [editName, setEditName] = useState("");
  const [editRawText, setEditRawText] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);

  async function loadResumes(preferredId?: string) {
    setLoading(true);
    try {
      const result = await getResumes();
      setResumes(result.items);
      const next = result.items.find((item) => item.id === preferredId) ?? result.items[0] ?? null;
      setSelected(next);
      if (next) setChunks(await getResumeChunks(next.id));
      else setChunks([]);
      setError(null);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "无法加载简历，请确认 API 服务已启动。 ");
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    void loadResumes();
  }, []);

  async function selectResume(resume: Resume) {
    setSelected(resume);
    try {
      setChunks(await getResumeChunks(resume.id));
      setError(null);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "无法加载简历 Chunk。 ");
    }
  }

  async function handleUpload(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!file) {
      setError("请先选择 PDF、DOCX、TXT 或 Markdown 文件。");
      return;
    }
    setUploading(true);
    setError(null);
    try {
      const resume = await uploadResume(file, name);
      setFile(null);
      setName("");
      const input = document.getElementById("resume-file") as HTMLInputElement | null;
      if (input) input.value = "";
      await loadResumes(resume.id);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "简历上传失败。");
    } finally {
      setUploading(false);
    }
  }

  async function handleParse() {
    if (!selected) return;
    setParsing(true);
    setError(null);
    try {
      const resume = await parseResume(selected.id);
      await loadResumes(resume.id);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "简历重新解析失败。");
    } finally {
      setParsing(false);
    }
  }

  function beginEdit() {
    if (!selected) return;
    setEditName(selected.name);
    setEditRawText(selected.raw_text);
    setEditing(true);
  }

  async function handleSave() {
    if (!selected || !editName.trim() || !editRawText.trim()) return;
    setSaving(true);
    setError(null);
    try {
      const updated = await updateResume(selected.id, {
        name: editName.trim(),
        raw_text: editRawText.trim(),
      });
      await loadResumes(updated.id);
      setEditing(false);
      setNotice("简历信息已保存，结构化档案和匹配向量已同步更新。");
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "简历保存失败。");
    } finally {
      setSaving(false);
    }
  }

  async function handleSetDefault() {
    if (!selected || selected.is_default) return;
    setSaving(true);
    setError(null);
    try {
      const updated = await updateResume(selected.id, { is_default: true });
      await loadResumes(updated.id);
      setNotice("已设为默认简历，后续匹配和 Agent 将优先使用该版本。");
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "默认简历设置失败。");
    } finally {
      setSaving(false);
    }
  }

  async function handleDelete() {
    if (!selected || !window.confirm(`确定删除简历“${selected.name}”吗？此操作不可撤销。`)) return;
    setSaving(true);
    setError(null);
    try {
      await deleteResume(selected.id);
      await loadResumes();
      setEditing(false);
      setNotice("简历已删除。");
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "简历删除失败。");
    } finally {
      setSaving(false);
    }
  }

  return (
    <div className="mx-auto max-w-6xl space-y-8">
      <header className="flex flex-wrap items-end justify-between gap-4">
        <div>
        <p className="eyebrow">简历智能中心</p>
        <h1 className="mt-3 text-3xl font-semibold tracking-tight">简历管理</h1>
        <p className="mt-3 text-slate-500">上传一次，持续维护结构化档案、匹配分块与向量索引。</p>
        </div>
        <span className="rounded-full bg-indigo-50 px-4 py-2 text-sm font-medium text-indigo-700">PDF · DOCX · TXT</span>
      </header>

      {error && <div className="rounded-xl border border-rose-200 bg-rose-50 p-4 text-rose-800">{error}</div>}
      {notice && <div className="rounded-xl border border-emerald-200 bg-emerald-50 p-4 text-emerald-800">{notice}</div>}

      <section className="panel">
        <div>
          <p className="eyebrow">导入简历</p>
          <h2 className="mt-2 text-xl font-semibold">上传新简历</h2>
          <p className="mt-2 text-sm text-slate-500">支持 PDF、DOCX、TXT、Markdown，单文件最大 10 MB。</p>
        </div>
        <form className="mt-6 grid gap-4 md:grid-cols-[1fr_220px_auto] md:items-end" onSubmit={handleUpload}>
          <label className="block text-sm font-medium text-slate-700" htmlFor="resume-file">
            文件
            <input
              accept={supportedFiles}
              className="mt-2 block w-full rounded-xl border border-slate-200 bg-white px-3 py-3 text-sm file:mr-3 file:rounded-lg file:border-0 file:bg-indigo-50 file:px-3 file:py-2 file:font-medium file:text-indigo-700"
              id="resume-file"
              onChange={(event) => setFile(event.target.files?.[0] ?? null)}
              type="file"
            />
          </label>
          <label className="block text-sm font-medium text-slate-700" htmlFor="resume-name">
            显示名称（可选）
            <input className="mt-2 w-full rounded-xl border border-slate-200 px-4 py-3 outline-none focus:border-indigo-500 focus:ring-4 focus:ring-indigo-100" id="resume-name" onChange={(event) => setName(event.target.value)} placeholder="例如：后端工程师版" value={name} />
          </label>
          <button className="rounded-xl bg-indigo-600 px-5 py-3 font-medium text-white transition hover:bg-indigo-700 disabled:cursor-not-allowed disabled:opacity-50" disabled={uploading} type="submit">
            {uploading ? "解析中…" : "上传并解析"}
          </button>
        </form>
      </section>

      <div className="grid gap-8 xl:grid-cols-[280px_1fr]">
        <section className="panel h-fit">
          <div className="flex items-center justify-between gap-3">
            <div>
              <p className="eyebrow">简历版本</p>
              <h2 className="mt-2 text-xl font-semibold">我的简历</h2>
            </div>
            <span className="text-sm text-slate-400">{resumes.length}</span>
          </div>
          <div className="mt-5 space-y-2">
            {loading && <p className="text-sm text-slate-400">加载中…</p>}
            {!loading && resumes.length === 0 && <p className="text-sm leading-6 text-slate-400">还没有简历，先上传一份建立候选人档案。</p>}
            {resumes.map((resume) => (
              <button key={resume.id} className={`w-full rounded-xl border p-4 text-left transition ${selected?.id === resume.id ? "border-indigo-300 bg-indigo-50" : "border-slate-200 hover:border-indigo-200 hover:bg-slate-50"}`} onClick={() => void selectResume(resume)} type="button">
                <p className="truncate font-medium text-slate-800">{resume.name}</p>
                <p className="mt-1 truncate text-xs text-slate-500">{resume.original_filename ?? "未知文件"}</p>
                <div className="mt-3 flex items-center justify-between text-xs text-slate-400">
                  <span>{resume.chunk_count} 个分块</span>
                  <span>{resume.is_default ? "默认" : formatDate(resume.created_at)}</span>
                </div>
              </button>
            ))}
          </div>
        </section>

        <div className="space-y-8">
          {selected ? (
            <>
              <section className="panel">
                <div className="flex flex-wrap items-start justify-between gap-4">
                  <div>
                    <p className="eyebrow">智能解析结果</p>
                    <h2 className="mt-2 text-2xl font-semibold">{selected.name}</h2>
                    <p className="mt-2 text-sm text-slate-500">{selected.original_filename} · v{selected.version} · 更新于 {formatDate(selected.updated_at)}</p>
                  </div>
                  <div className="flex flex-wrap gap-2">
                    {!selected.is_default && <button className="rounded-xl border border-indigo-200 px-4 py-2 text-sm font-medium text-indigo-700" disabled={saving} onClick={() => void handleSetDefault()} type="button">设为默认</button>}
                    <button className="rounded-xl border border-slate-200 px-4 py-2 text-sm font-medium text-slate-700 transition hover:border-indigo-300 hover:text-indigo-700" disabled={saving} onClick={beginEdit} type="button">编辑</button>
                    <button className="rounded-xl border border-slate-200 px-4 py-2 text-sm font-medium text-slate-700 transition hover:border-indigo-300 hover:text-indigo-700 disabled:cursor-not-allowed disabled:opacity-50" disabled={parsing || saving} onClick={() => void handleParse()} type="button">{parsing ? "重新解析中…" : "重新解析"}</button>
                    <button className="rounded-xl border border-rose-200 px-4 py-2 text-sm font-medium text-rose-700 transition hover:bg-rose-50" disabled={saving} onClick={() => void handleDelete()} type="button">删除</button>
                  </div>
                </div>
                {editing && <div className="mt-6 rounded-2xl border border-indigo-200 bg-indigo-50/50 p-5">
                  <div className="grid gap-4">
                    <label className="text-sm font-medium text-slate-700">简历名称<input className="mt-2 w-full rounded-xl border border-slate-200 bg-white px-4 py-3 font-normal outline-none focus:border-indigo-500" onChange={(event) => setEditName(event.target.value)} value={editName} /></label>
                    <label className="text-sm font-medium text-slate-700">简历原文<textarea className="mt-2 min-h-64 w-full rounded-xl border border-slate-200 bg-white px-4 py-3 font-mono text-sm font-normal leading-6 outline-none focus:border-indigo-500" onChange={(event) => setEditRawText(event.target.value)} value={editRawText} /></label>
                  </div>
                  <div className="mt-4 flex gap-2"><button className="rounded-xl bg-indigo-600 px-4 py-2 text-sm font-medium text-white disabled:opacity-50" disabled={saving || !editName.trim() || !editRawText.trim()} onClick={() => void handleSave()} type="button">{saving ? "保存中…" : "保存并重新解析"}</button><button className="rounded-xl border border-slate-200 bg-white px-4 py-2 text-sm text-slate-700" onClick={() => setEditing(false)} type="button">取消</button></div>
                </div>}
                <div className="mt-6"><ProfileList profile={selected.structured_profile} /></div>
              </section>

              <details className="panel group">
                <summary className="flex cursor-pointer list-none flex-wrap items-end justify-between gap-3">
                  <div>
                    <p className="eyebrow">匹配数据</p>
                    <h2 className="mt-2 text-xl font-semibold">语义分块与向量</h2>
                    <p className="mt-2 text-sm font-normal text-slate-500">用于职位匹配的底层数据，通常无需查看。</p>
                  </div>
                  <span className="text-sm font-normal text-slate-500">{chunks.length} 个分块 · 点击展开</span>
                </summary>
                <div className="mt-5"><ChunkList chunks={chunks} /></div>
              </details>

              <details className="panel group">
                <summary className="cursor-pointer font-semibold text-slate-800">查看原始文本</summary>
                <pre className="mt-4 max-h-96 overflow-auto whitespace-pre-wrap rounded-xl bg-slate-950 p-4 text-sm leading-6 text-slate-200">{maskPersonalInfo(selected.raw_text)}</pre>
              </details>
            </>
          ) : (
            <section className="panel grid min-h-80 place-items-center border-dashed text-center">
              <div>
                <div className="mx-auto grid h-14 w-14 place-items-center rounded-2xl bg-indigo-50 text-2xl text-indigo-600">↥</div>
                <h2 className="mt-4 text-lg font-semibold">还没有选中的简历</h2>
                <p className="mt-2 text-sm text-slate-500">上传简历后，这里会展示结构化经历、技能和匹配数据。</p>
              </div>
            </section>
          )}
        </div>
      </div>
    </div>
  );
}
