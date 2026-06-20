import { useCallback, useEffect, useRef, useState } from "react";

import {
  activateResume,
  deleteResume,
  fetchMe,
  listResumes,
  loginUrl,
  logout,
  uploadResume,
} from "./api.js";
import ExtensionCard from "./ExtensionCard.jsx";

const PARSE_LABEL = {
  0: { text: "解析中", cls: "badge-wait" },
  1: { text: "可用", cls: "badge-ok" },
  2: { text: "解析失败", cls: "badge-fail" },
};

const UPLOAD_STAGE = {
  signing: "申请上传地址…",
  uploading: "上传到云端…",
  parsing: "解析简历文本…",
};

function formatSize(bytes) {
  if (!bytes && bytes !== 0) return "—";
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / 1024 / 1024).toFixed(1)} MB`;
}

function formatDate(iso) {
  if (!iso) return "";
  try {
    return new Date(iso).toLocaleString("zh-CN", { hour12: false });
  } catch {
    return iso;
  }
}

export default function App() {
  const [me, setMe] = useState(undefined); // undefined=加载中 / null=未登录 / object=已登录
  const [resumes, setResumes] = useState([]);
  const [stage, setStage] = useState(null);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const fileInput = useRef(null);

  const refreshResumes = useCallback(async () => {
    try {
      setResumes(await listResumes());
    } catch (err) {
      if (err.code === 401) setMe(null);
      else setError(err.message);
    }
  }, []);

  useEffect(() => {
    fetchMe()
      .then((data) => {
        setMe(data.user || null);
        if (data.user) refreshResumes();
      })
      .catch(() => setMe(null));
  }, [refreshResumes]);

  const onPick = () => fileInput.current?.click();

  const onFile = async (event) => {
    const file = event.target.files?.[0];
    event.target.value = ""; // 允许再次选同一文件
    if (!file) return;
    if (file.type && file.type !== "application/pdf" && !file.name.toLowerCase().endsWith(".pdf")) {
      setError("目前仅支持 PDF 简历。");
      return;
    }
    setError("");
    setNotice("");
    try {
      const resume = await uploadResume(file, setStage);
      setStage(null);
      if (resume.parse_status === 2) {
        setError(resume.parse_error || "简历解析失败，请换一份可复制文本的 PDF。");
      } else {
        setNotice("上传成功，已设为当前生效简历。");
      }
      await refreshResumes();
    } catch (err) {
      setStage(null);
      if (err.code === 401) setMe(null);
      else setError(err.message);
    }
  };

  const onActivate = async (id) => {
    setError("");
    try {
      await activateResume(id);
      await refreshResumes();
    } catch (err) {
      setError(err.message);
    }
  };

  const onDelete = async (id) => {
    setError("");
    try {
      await deleteResume(id);
      await refreshResumes();
    } catch (err) {
      setError(err.message);
    }
  };

  const onLogout = async () => {
    await logout().catch(() => {});
    setMe(null);
    setResumes([]);
  };

  return (
    <div className="page">
      <header className="topbar">
        <div className="brand">
          <span className="mark" aria-hidden="true">⌁</span>
          <span className="wordmark">AGENT BRIDGE</span>
          <span className="subtitle">简历管理</span>
        </div>
        {me && (
          <div className="user">
            <span className="user-name">{me.display_name || me.username || me.email || "已登录"}</span>
            <button className="btn-ghost" onClick={onLogout}>退出登录</button>
          </div>
        )}
      </header>

      <main className="content">
        {me === undefined && <p className="muted">加载中…</p>}

        {me === null && (
          <section className="card signin">
            <h1>登录以管理你的简历</h1>
            <p className="muted">
              登录后上传的简历会用于浏览器扩展的「与简历匹配」功能。简历文本仅用于为你生成匹配分析。
            </p>
            <a className="btn-primary" href={loginUrl}>使用 Casdoor 登录</a>
          </section>
        )}

        {me && (
          <>
            <section className="card uploader">
              <div className="uploader-head">
                <div>
                  <h2>上传简历</h2>
                  <p className="muted">支持 PDF；上传成功的最新简历会自动设为「生效」，匹配时使用它。</p>
                </div>
                <button className="btn-primary" onClick={onPick} disabled={!!stage}>
                  {stage ? UPLOAD_STAGE[stage] : "选择 PDF 上传"}
                </button>
              </div>
              <input
                ref={fileInput}
                type="file"
                accept="application/pdf,.pdf"
                onChange={onFile}
                hidden
              />
              {stage && <div className="progress"><span /></div>}
            </section>

            <ExtensionCard />

            {error && <div className="alert alert-error">{error}</div>}
            {notice && <div className="alert alert-ok">{notice}</div>}

            <section className="card list">
              <h2>我的简历 <span className="count">{resumes.length}</span></h2>
              {resumes.length === 0 ? (
                <p className="muted empty">还没有简历，点上方按钮上传第一份。</p>
              ) : (
                <ul className="resume-list">
                  {resumes.map((r) => {
                    const badge = PARSE_LABEL[r.parse_status] || PARSE_LABEL[0];
                    return (
                      <li key={r.id} className={r.is_active ? "resume active" : "resume"}>
                        <div className="resume-main">
                          <span className="resume-name" title={r.filename || r.id}>
                            {r.filename || "未命名简历"}
                          </span>
                          <div className="resume-meta">
                            <span className={`badge ${badge.cls}`}>{badge.text}</span>
                            {r.is_active && <span className="badge badge-active">生效中</span>}
                            <span className="muted">{formatSize(r.file_size)}</span>
                            <span className="muted">{r.text_chars} 字</span>
                            <span className="muted">{formatDate(r.created_at)}</span>
                          </div>
                          {r.parse_status === 2 && r.parse_error && (
                            <p className="resume-error">{r.parse_error}</p>
                          )}
                        </div>
                        <div className="resume-actions">
                          {r.parse_status === 1 && !r.is_active && (
                            <button className="btn-ghost" onClick={() => onActivate(r.id)}>设为生效</button>
                          )}
                          <button className="btn-ghost danger" onClick={() => onDelete(r.id)}>删除</button>
                        </div>
                      </li>
                    );
                  })}
                </ul>
              )}
            </section>
          </>
        )}
      </main>
    </div>
  );
}
