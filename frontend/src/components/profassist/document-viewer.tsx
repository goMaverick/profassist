"use client";

import { useEffect, useState } from "react";
import { getDocument, GlobalWorkerOptions, TextLayer } from "pdfjs-dist";

GlobalWorkerOptions.workerSrc = "/pdf.worker.min.mjs";

export interface Box {
  x: number;
  y: number;
  w: number;
  h: number;
}

export interface Hit {
  id: string;
  n: number;
  page: number;
  box: Box;
  tone: "shared" | "brief" | "readings";
}

export interface MarginNote {
  id: string;
  page: number;
  box: Box;
  text: string;
  quote?: string;
}

export function fileUrl(path: string) {
  return `/api/profassist${path}`;
}

export function DocumentPane({
  url,
  title,
  subtitle,
  downloadUrl,
  hits = [],
  activeId,
  notes = [],
  allowSelection = false,
  onSelectText,
  onEditNote,
  onDeleteNote,
}: {
  url: string;
  title: string;
  subtitle?: string;
  downloadUrl?: string;
  hits?: Hit[];
  activeId?: string;
  notes?: MarginNote[];
  allowSelection?: boolean;
  onSelectText?: (pick: { page: number; quote: string; box: Box }) => void;
  onEditNote?: (id: string, text: string) => void;
  onDeleteNote?: (id: string) => void;
}) {
  const [pdf, setPdf] = useState<Awaited<ReturnType<typeof loadPdf>> | null>(null);
  const [pages, setPages] = useState(0);
  const [scale, setScale] = useState(0.9);
  const [failed, setFailed] = useState("");

  useEffect(() => {
    let cancelled = false;
    setFailed("");
    const task = getDocument({ url, withCredentials: true });
    task.promise
      .then((document) => {
        if (cancelled) return;
        setPdf(document);
        setPages(document.numPages);
      })
      .catch(() => {
        if (!cancelled) setFailed("The document could not be opened.");
      });
    return () => {
      cancelled = true;
      void task.destroy();
    };
  }, [url]);

  const pane = title.replace(/\s+/g, "-");

  useEffect(() => {
    if (!activeId) return;
    document.getElementById(`hit-${pane}-${activeId}`)?.scrollIntoView({ behavior: "smooth", block: "center" });
  }, [activeId, pages, scale, pane]);

  return (
    <section className="pa-doc">
      <header className="pa-doc-head">
        <div>
          <strong>{title}</strong>
          {subtitle && <span>{subtitle}</span>}
        </div>
        <div className="pa-doc-tools">
          <button type="button" onClick={() => setScale((value) => Math.max(0.8, value - 0.15))}>Smaller</button>
          <button type="button" onClick={() => setScale((value) => Math.min(1.6, value + 0.15))}>Larger</button>
          {downloadUrl && <a href={downloadUrl}>Download original</a>}
        </div>
      </header>
      {failed && <p role="alert">{failed}</p>}
      <div className="pa-thumbs" aria-label="Pages">
        {Array.from({ length: pages }, (_, index) => (
          <button key={index} type="button" onClick={() => document.getElementById(`page-${title}-${index + 1}`)?.scrollIntoView({ behavior: "smooth", block: "start" })}>
            {pdf && <Thumb pdf={pdf} page={index + 1} pane={pane} />}
            <span>Page {index + 1}</span>
          </button>
        ))}
      </div>
      <div className="pa-doc-scroll">
        {Array.from({ length: pages }, (_, index) => (
          <PageView
            key={`${url}-${index}-${scale}`}
            pdf={pdf}
            pageNumber={index + 1}
            scale={scale}
            title={title}
            pane={pane}
            hits={hits.filter((hit) => hit.page === index + 1)}
            notes={notes.filter((note) => note.page === index + 1)}
            activeId={activeId}
            allowSelection={allowSelection}
            onSelectText={onSelectText}
            onEditNote={onEditNote}
            onDeleteNote={onDeleteNote}
          />
        ))}
      </div>
    </section>
  );
}

async function loadPdf(url: string) {
  return getDocument({ url, withCredentials: true }).promise;
}

function Thumb({ pdf, page, pane }: { pdf: Awaited<ReturnType<typeof loadPdf>>; page: number; pane: string }) {
  const [ready, setReady] = useState(false);
  useEffect(() => {
    let cancelled = false;
    const canvas = document.getElementById(`thumb-${pane}-${page}`) as HTMLCanvasElement | null;
    if (!canvas) return;
    pdf.getPage(page).then(async (sheet) => {
      if (cancelled) return;
      const viewport = sheet.getViewport({ scale: 0.16 });
      canvas.width = viewport.width;
      canvas.height = viewport.height;
      await sheet.render({ canvas, viewport }).promise;
      if (!cancelled) setReady(true);
    }).catch(() => undefined);
    return () => {
      cancelled = true;
    };
  }, [pdf, page, pane]);
  return <canvas id={`thumb-${pane}-${page}`} data-ready={ready} />;
}

function PageView({
  pdf,
  pageNumber,
  scale,
  title,
  pane,
  hits,
  notes,
  activeId,
  allowSelection,
  onSelectText,
  onEditNote,
  onDeleteNote,
}: {
  pdf: Awaited<ReturnType<typeof loadPdf>> | null;
  pageNumber: number;
  scale: number;
  title: string;
  pane: string;
  hits: Hit[];
  notes: MarginNote[];
  activeId?: string;
  allowSelection?: boolean;
  onSelectText?: (pick: { page: number; quote: string; box: Box }) => void;
  onEditNote?: (id: string, text: string) => void;
  onDeleteNote?: (id: string) => void;
}) {
  const [size, setSize] = useState({ width: 0, height: 0 });

  useEffect(() => {
    if (!pdf) return;
    let cancelled = false;
    pdf.getPage(pageNumber).then(async (sheet) => {
      if (cancelled) return;
      const viewport = sheet.getViewport({ scale });
      const canvas = document.getElementById(`canvas-${title}-${pageNumber}`) as HTMLCanvasElement | null;
      const textLayer = document.getElementById(`text-${title}-${pageNumber}`);
      if (!canvas) return;
      canvas.width = viewport.width;
      canvas.height = viewport.height;
      setSize({ width: viewport.width, height: viewport.height });
      await sheet.render({ canvas, viewport }).promise;
      if (textLayer && allowSelection) {
        textLayer.replaceChildren();
        textLayer.style.setProperty("--total-scale-factor", String(scale));
        const layer = new TextLayer({
          textContentSource: sheet.streamTextContent(),
          container: textLayer,
          viewport,
        });
        await layer.render();
      }
    }).catch(() => undefined);
    return () => {
      cancelled = true;
    };
  }, [pdf, pageNumber, scale, title, allowSelection]);

  function selectText() {
    if (!onSelectText) return;
    const selection = window.getSelection();
    if (!selection || selection.isCollapsed) return;
    const host = document.getElementById(`page-${title}-${pageNumber}`);
    if (!host) return;
    const range = selection.getRangeAt(0);
    const rect = range.getBoundingClientRect();
    const page = host.getBoundingClientRect();
    const quote = selection.toString().trim();
    if (!quote) return;
    onSelectText({
      page: pageNumber,
      quote,
      box: {
        x: (rect.left - page.left) / page.width,
        y: (rect.top - page.top) / page.height,
        w: rect.width / page.width,
        h: Math.max(rect.height, 10) / page.height,
      },
    });
  }

  return (
    <article id={`page-${title}-${pageNumber}`} className="pa-page" style={{ width: size.width || undefined }} onMouseUp={selectText}>
      <canvas id={`canvas-${title}-${pageNumber}`} />
      <div id={`text-${title}-${pageNumber}`} className="pa-text-layer" />
      {hits.map((hit) => (
        <span
          key={hit.id}
          id={`hit-${pane}-${hit.id}`}
          className={`pa-hit pa-hit-${hit.tone}${hit.id === activeId ? " pa-pulse" : ""}`}
          style={{ left: `${hit.box.x * 100}%`, top: `${hit.box.y * 100}%`, width: `${hit.box.w * 100}%`, height: `${hit.box.h * 100}%` }}
        >
          {hit.n > 0 && <i>{hit.n}</i>}
        </span>
      ))}
      {notes.map((note) => (
        <span
          key={`${note.id}-mark`}
          className="pa-hit pa-hit-note"
          style={{ left: `${note.box.x * 100}%`, top: `${note.box.y * 100}%`, width: `${note.box.w * 100}%`, height: `${note.box.h * 100}%` }}
        />
      ))}
      {notes.map((note) => (
        <aside key={note.id} className="pa-bubble" style={{ top: `${note.box.y * 100}%` }}>
          <textarea aria-label="Comment" value={note.text} onChange={(event) => onEditNote?.(note.id, event.target.value)} />
          <button type="button" onClick={() => onDeleteNote?.(note.id)}>Delete</button>
        </aside>
      ))}
    </article>
  );
}
