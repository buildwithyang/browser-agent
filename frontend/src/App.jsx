import { useCallback, useEffect, useRef, useState } from "react";

import {
  activateResume,
  deleteResume,
  fetchMe,
  listResumes,
  logout,
  uploadResume,
} from "./api.js";
import ExtensionCard from "./ExtensionCard.jsx";
import Landing from "./Landing.jsx";
import { useI18n, LanguageToggle } from "./i18n.jsx";

const PARSE_LABEL = {
  0: { key: "app.badge.wait", cls: "badge-wait" },
  1: { key: "app.badge.ok", cls: "badge-ok" },
  2: { key: "app.badge.fail", cls: "badge-fail" },
};

const UPLOAD_STAGE = {
  signing: "app.upload.stageSigning",
  uploading: "app.upload.stageUploading",
  parsing: "app.upload.stageParsing",
};

function formatSize(bytes) {
  if (!bytes && bytes !== 0) return "—";
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / 1024 / 1024).toFixed(1)} MB`;
}

function formatDate(iso, lang) {
  if (!iso) return "";
  try {
    return new Date(iso).toLocaleString(lang === "zh" ? "zh-CN" : "en-US", { hour12: false });
  } catch {
    return iso;
  }
}

export default function App() {
  const { t, lang } = useI18n();
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
      setError(t("app.upload.errPdfOnly"));
      return;
    }
    setError("");
    setNotice("");
    try {
      const resume = await uploadResume(file, setStage);
      setStage(null);
      if (resume.parse_status === 2) {
        setError(resume.parse_error || t("app.upload.errParse"));
      } else {
        setNotice(t("app.upload.ok"));
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

  // 未登录 -> 落地页(自带导航/页脚,负责拉新与登录入口)。
  if (me === null) return <Landing />;

  return (
    <div className="page">
      <header className="topbar">
        <div className="brand">
          <span className="mark" aria-hidden="true">⌁</span>
          <span className="wordmark">AGENT BRIDGE</span>
          <span className="subtitle">{t("app.brandSubtitle")}</span>
        </div>
        <LanguageToggle />
        {me && (
          <div className="user">
            <span className="user-name">{me.display_name || me.username || me.email || t("app.loggedInFallback")}</span>
            <button className="btn-ghost" onClick={onLogout}>{t("nav.logout")}</button>
          </div>
        )}
      </header>

      <main className="content">
        {me === undefined && <p className="muted">{t("app.loading")}</p>}

        {me && (
          <>
            <section className="card uploader">
              <div className="uploader-head">
                <div>
                  <h2>{t("app.upload.title")}</h2>
                  <p className="muted">{t("app.upload.desc")}</p>
                </div>
                <button className="btn-primary" onClick={onPick} disabled={!!stage}>
                  {stage ? t(UPLOAD_STAGE[stage]) : t("app.upload.pick")}
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
              <h2>{t("app.list.title")} <span className="count">{resumes.length}</span></h2>
              {resumes.length === 0 ? (
                <p className="muted empty">{t("app.list.empty")}</p>
              ) : (
                <ul className="resume-list">
                  {resumes.map((r) => {
                    const badge = PARSE_LABEL[r.parse_status] || PARSE_LABEL[0];
                    return (
                      <li key={r.id} className={r.is_active ? "resume active" : "resume"}>
                        <div className="resume-main">
                          <span className="resume-name" title={r.filename || r.id}>
                            {r.filename || t("app.list.unnamed")}
                          </span>
                          <div className="resume-meta">
                            <span className={`badge ${badge.cls}`}>{t(badge.key)}</span>
                            {r.is_active && <span className="badge badge-active">{t("app.badge.active")}</span>}
                            <span className="muted">{formatSize(r.file_size)}</span>
                            <span className="muted">{t("app.list.chars", { n: r.text_chars })}</span>
                            <span className="muted">{formatDate(r.created_at, lang)}</span>
                          </div>
                          {r.parse_status === 2 && r.parse_error && (
                            <p className="resume-error">{r.parse_error}</p>
                          )}
                        </div>
                        <div className="resume-actions">
                          {r.parse_status === 1 && !r.is_active && (
                            <button className="btn-ghost" onClick={() => onActivate(r.id)}>{t("app.list.setActive")}</button>
                          )}
                          <button className="btn-ghost danger" onClick={() => onDelete(r.id)}>{t("app.list.delete")}</button>
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

      <footer className="footer">
        <a href="/privacy" target="_blank" rel="noopener noreferrer">{t("app.footerPrivacy")}</a>
      </footer>
    </div>
  );
}
