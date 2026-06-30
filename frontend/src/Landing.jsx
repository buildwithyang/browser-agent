import { useEffect, useRef, useState } from "react";

import { loginUrl, extensionStoreUrl } from "./api.js";
import { useI18n, LanguageToggle } from "./i18n.jsx";

// 浏览器是否要求减弱动效;减弱时直接给终态,不播放序列。
const prefersReducedMotion =
  typeof window !== "undefined" &&
  window.matchMedia &&
  window.matchMedia("(prefers-reduced-motion: reduce)").matches;

// hero 评分从 0 数到 target;减弱动效时直接显示 target。
function useCountUp(target, enabled) {
  const [value, setValue] = useState(enabled ? 0 : target);
  useEffect(() => {
    if (!enabled) {
      setValue(target);
      return;
    }
    let raf;
    let start;
    const duration = 1100;
    const tick = (t) => {
      if (start === undefined) start = t;
      const p = Math.min(1, (t - start) / duration);
      const eased = 1 - Math.pow(1 - p, 3); // easeOutCubic
      setValue(Math.round(target * eased));
      if (p < 1) raf = requestAnimationFrame(tick);
    };
    raf = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(raf);
  }, [target, enabled]);
  return value;
}

// 元素滚动进入视口时加 .in,触发一次性揭示动画。
function useReveal() {
  const ref = useRef(null);
  useEffect(() => {
    const node = ref.current;
    if (!node) return;
    if (prefersReducedMotion || !("IntersectionObserver" in window)) {
      node.classList.add("in");
      return;
    }
    const io = new IntersectionObserver(
      (entries) => {
        entries.forEach((e) => {
          if (e.isIntersecting) {
            e.target.classList.add("in");
            io.unobserve(e.target);
          }
        });
      },
      { threshold: 0.18 }
    );
    io.observe(node);
    return () => io.disconnect();
  }, []);
  return ref;
}

function Instrument() {
  const { t } = useI18n();
  const score = useCountUp(87, !prefersReducedMotion);
  return (
    <div className="lp-inst" aria-hidden="true">
      <div className="lp-inst-head">
        <span className="mark">⌁</span>
        <span className="wordmark">AGENT BRIDGE</span>
      </div>
      <div className="lp-inst-body">
        <div className="lp-bridge">
          <span className="lp-end lp-end-job">
            <i />{t("landing.inst.job")}
          </span>
          <span className="lp-rail">
            <b className="lp-pulse" />
          </span>
          <span className="lp-end lp-end-cv">
            {t("landing.inst.cv")}<i />
          </span>
        </div>

        <div className="lp-readout">
          <div className="lp-score">
            <span className="lp-score-num">{score}</span>
            <span className="lp-score-unit">/100</span>
          </div>
          <div className="lp-score-label">{t("landing.inst.scoreLabel")}</div>
        </div>

        <div className="lp-chips">
          <div className="lp-chip lp-chip-ok">
            <span>{t("landing.inst.ok")}</span>{t("landing.inst.chip1")}
          </div>
          <div className="lp-chip lp-chip-ok">
            <span>{t("landing.inst.ok")}</span>{t("landing.inst.chip2")}
          </div>
          <div className="lp-chip lp-chip-gap">
            <span>{t("landing.inst.gap")}</span>{t("landing.inst.chip3")}
          </div>
        </div>
      </div>
    </div>
  );
}

export default function Landing() {
  const { t } = useI18n();
  const stepsRef = useReveal();
  const featRef = useReveal();
  const ctaRef = useReveal();

  const steps = t("landing.steps");
  const features = t("landing.features");

  return (
    <div className="lp">
      <header className="lp-topbar">
        <div className="brand">
          <span className="mark" aria-hidden="true">⌁</span>
          <span className="wordmark">AGENT BRIDGE</span>
        </div>
        <nav className="lp-nav">
          <LanguageToggle />
          <a className="btn-ghost" href={loginUrl}>{t("nav.login")}</a>
          <a
            className="btn-primary"
            href={extensionStoreUrl}
            target="_blank"
            rel="noopener noreferrer"
          >
            {t("nav.addChrome")}
          </a>
        </nav>
      </header>

      <main className="lp-main">
        <section className="lp-hero">
          <div className="lp-hero-copy">
            <p className="lp-eyebrow">{t("landing.eyebrow")}</p>
            <h1 className="lp-h1">
              {t("landing.h1a")}<br />
              {t("landing.h1b")}<br />
              <em>{t("landing.h1em")}</em>
            </h1>
            <p className="lp-sub">{t("landing.sub")}</p>
            <div className="lp-cta">
              <a
                className="btn-primary lp-cta-main"
                href={extensionStoreUrl}
                target="_blank"
                rel="noopener noreferrer"
              >
                {t("landing.ctaMain")}
              </a>
              <a className="lp-cta-alt" href={loginUrl}>
                {t("landing.ctaAlt")}
              </a>
            </div>
            <p className="lp-trust">{t("landing.trust")}</p>
          </div>

          <div className="lp-hero-art">
            <Instrument />
          </div>
        </section>

        <section className="lp-steps" ref={stepsRef}>
          <p className="lp-section-eyebrow">{t("landing.stepsEyebrow")}</p>
          <div className="lp-steps-grid">
            {steps.map((s) => (
              <div className="lp-step" key={s.n}>
                <span className="lp-step-n">{s.n}</span>
                <h3 className="lp-step-title">{s.title}</h3>
                <p className="lp-step-body">{s.body}</p>
              </div>
            ))}
          </div>
        </section>

        <section className="lp-features" ref={featRef}>
          <p className="lp-section-eyebrow">{t("landing.featuresEyebrow")}</p>
          <div className="lp-feature-grid">
            {features.map((f) => (
              <div className="lp-feature" key={f.tag}>
                <span className="lp-feature-tag">{f.tag}</span>
                <p className="lp-feature-body">{f.body}</p>
              </div>
            ))}
          </div>
        </section>

        <section className="lp-close" ref={ctaRef}>
          <h2 className="lp-close-h">{t("landing.closeH")}</h2>
          <a
            className="btn-primary lp-cta-main"
            href={extensionStoreUrl}
            target="_blank"
            rel="noopener noreferrer"
          >
            {t("landing.ctaMain")}
          </a>
        </section>
      </main>

      <footer className="lp-footer">
        <span>{t("landing.footerNote")}</span>
        <a href={loginUrl}>{t("landing.footerLink")}</a>
      </footer>
    </div>
  );
}
