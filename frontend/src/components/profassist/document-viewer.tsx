"use client";

import { useEffect, useRef, useState } from "react";
import { Button, Tag, TextArea } from "@carbon/react";
import { Download, Edit, TrashCan, ZoomIn, ZoomOut } from "@carbon/icons-react";
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
  kind = "pdf",
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
  kind?: "pdf" | "docx";
  downloadUrl?: string;
  hits?: Hit[];
  activeId?: string;
  notes?: MarginNote[];
  allowSelection?: boolean;
  onSelectText?: (pick: { page: number; quote: string; box: Box }) => void;
  onEditNote?: (id: string, text: string) => void;
  onDeleteNote?: (id: string) => void;
}) {
  const frame = useRef<HTMLDivElement>(null);
  const [pdf, setPdf] = useState<Awaited<ReturnType<typeof loadPdf>> | null>(null);
  const [pages, setPages] = useState(0);
  const [scale, setScale] = useState(1.27);
  const [failed, setFailed] = useState("");
  const fitted = useRef(false);

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
  const activePage = hits.find((hit) => hit.id === activeId)?.page || notes[0]?.page || 1;

  useEffect(() => {
    const node = frame.current;
    if (!node || !pages || fitted.current) return;
    const styles = getComputedStyle(node);
    const pad = parseFloat(styles.paddingLeft) + parseFloat(styles.paddingRight);
    const gutter = node.classList.contains("has-notes") ? 220 : 0;
    const fit = (node.clientWidth - pad - gutter - 8) / 595;
    setScale(Math.min(1.45, Math.max(gutter ? 0.55 : 0.9, fit)));
    fitted.current = true;
  }, [pages]);

  useEffect(() => {
    if (!activeId) return;
    document.getElementById(`hit-${pane}-${activeId}`)?.scrollIntoView({ behavior: "smooth", block: "center" });
  }, [activeId, pages, scale, pane]);

  return (
    <section className="pa-doc">
      <header className="pa-doc-head">
        <div className="pa-doc-title">
          <strong>{title}</strong>
          <Tag size="sm" type={kind === "docx" ? "blue" : "gray"}>{kind === "docx" ? "Word, shown as PDF" : "PDF"}</Tag>
        </div>
        <div className="pa-doc-tools">
          <Button kind="ghost" size="sm" hasIconOnly renderIcon={ZoomOut} iconDescription="Zoom out" onClick={() => setScale((value) => Math.max(0.9, Number((value - 0.15).toFixed(2))))} />
          <Button kind="ghost" size="sm" hasIconOnly renderIcon={ZoomIn} iconDescription="Zoom in" onClick={() => setScale((value) => Math.min(1.9, Number((value + 0.15).toFixed(2))))} />
          {downloadUrl && <Button kind="ghost" size="sm" hasIconOnly renderIcon={Download} iconDescription="Download original" href={downloadUrl} />}
        </div>
      </header>
      {failed && <p role="alert">{failed}</p>}
      <div className="pa-thumbs" aria-label="Pages">
        {Array.from({ length: pages }, (_, index) => (
          <button key={index} type="button" className={index + 1 === activePage ? "is-active" : ""} onClick={() => document.getElementById(`page-${title}-${index + 1}`)?.scrollIntoView({ behavior: "smooth", block: "start" })}>
            {pdf && <Thumb pdf={pdf} page={index + 1} pane={pane} />}
            <span>{index + 1}</span>
          </button>
        ))}
      </div>
      <div className={`pa-doc-scroll${notes.length ? " has-notes" : ""}`} ref={frame}>
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
      const viewport = sheet.getViewport({ scale: 0.08 });
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
        <CommentCard key={note.id} note={note} onEdit={onEditNote} onDelete={onDeleteNote} />
      ))}
    </article>
  );
}

function CommentCard({
  note,
  onEdit,
  onDelete,
}: {
  note: MarginNote;
  onEdit?: (id: string, text: string) => void;
  onDelete?: (id: string) => void;
}) {
  const [editing, setEditing] = useState(false);
  const [text, setText] = useState(note.text);
  return (
    <aside className="pa-comment" style={{ top: `${note.box.y * 100}%` }}>
      <span className="pa-comment-line" />
      <div className="pa-comment-card">
        <span className="pa-avatar" aria-hidden="true">LH</span>
        <div>
          <div className="pa-comment-meta">
            <strong>You</strong>
            <time>22 Nov 2026</time>
          </div>
          {editing ? (
            <TextArea id={`comment-${note.id}`} labelText="Comment" hideLabel value={text} onChange={(event) => setText(event.target.value)} />
          ) : (
            <p>{note.text}</p>
          )}
          <div className="pa-comment-actions">
            <Button
              kind="ghost"
              size="sm"
              hasIconOnly
              renderIcon={Edit}
              iconDescription={editing ? "Save comment" : "Edit comment"}
              onClick={() => {
                if (editing) onEdit?.(note.id, text);
                setEditing((open) => !open);
              }}
            />
            <Button kind="ghost" size="sm" hasIconOnly renderIcon={TrashCan} iconDescription="Delete comment" onClick={() => onDelete?.(note.id)} />
          </div>
        </div>
      </div>
    </aside>
  );
}
