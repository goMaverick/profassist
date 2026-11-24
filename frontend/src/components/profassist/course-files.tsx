"use client";

import { useRef, useState } from "react";
import {
  CloudUpload,
  File as FileGlyph,
  FileCode,
  FileText,
  FileType2,
  Presentation,
  Trash2,
} from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Label } from "@/components/ui/label";
import { Progress } from "@/components/ui/progress";
import { Textarea } from "@/components/ui/textarea";
import { BADGE_TONE, insightBadge, kindLabel, kindTone } from "@/lib/profassist";

export interface CourseFile {
  id: string;
  filename: string;
  status: string;
  size?: number;
  scrubbed?: boolean;
  phase?: "uploading" | "ready" | "error";
  progress?: number;
  error?: string;
  insight_status?: string;
  kind?: string;
  tags?: string[];
  summary?: string;
  trace_url?: string;
}

const EXAMPLES = [
  "Focus on healthcare cases.",
  "Prefer a project a group can build in four weeks.",
  "Keep the assessments to four tasks that total 100%.",
  "Use the faculty wording for integrity and attendance.",
];

const LIMIT = 25 * 1024 * 1024;
const ACCEPT = ".pdf,.docx,.pptx,.potx,.html,.htm,.txt,.md";
const ALLOWED_EXTENSIONS = [".pdf", ".docx", ".pptx", ".potx", ".html", ".htm", ".txt", ".md"];

const TONES = BADGE_TONE;

export function CourseFiles({
  files,
  onUpload,
  onRemove,
  instructions,
  onInstructions,
}: {
  files: CourseFile[];
  onUpload: (file: File) => Promise<void>;
  onRemove: (file: CourseFile) => Promise<void>;
  instructions?: string;
  onInstructions?: (value: string) => void;
}) {
  const [over, setOver] = useState(false);
  const [local, setLocal] = useState<CourseFile[]>([]);
  const picker = useRef<HTMLInputElement>(null);
  const known = new Set(files.map((file) => file.filename));
  const pending = local.filter(
    (file) => file.phase === "uploading" || file.phase === "error" || !known.has(file.filename),
  );
  const shown = [...pending, ...files];

  async function add(incoming: File[]) {
    for (const file of incoming) {
      const id = `${file.name}-${file.size}-${Date.now()}`;
      if (file.size > LIMIT) {
        setLocal((current) => [
          {
            id,
            filename: file.name,
            status: "error",
            size: file.size,
            phase: "error",
            error: "That file is over 25 MB.",
          },
          ...current,
        ]);
        continue;
      }
      if (!ALLOWED_EXTENSIONS.some((ext) => file.name.toLowerCase().endsWith(ext))) {
        setLocal((current) => [
          {
            id,
            filename: file.name,
            status: "error",
            size: file.size,
            phase: "error",
            error: "Use a PDF, DOCX, PPTX, POTX, HTML, HTM, TXT, or MD file.",
          },
          ...current,
        ]);
        continue;
      }
      setLocal((current) => [
        {
          id,
          filename: file.name,
          status: "uploading",
          size: file.size,
          phase: "uploading",
          progress: 35,
        },
        ...current,
      ]);
      try {
        await onUpload(file);
        setLocal((current) =>
          current.map((item) =>
            item.id === id ? { ...item, phase: "ready", status: "ready", progress: 100 } : item,
          ),
        );
      } catch (err) {
        const message = err instanceof Error ? err.message : "The upload failed.";
        setLocal((current) =>
          current.map((item) =>
            item.id === id ? { ...item, phase: "error", status: "error", error: message } : item,
          ),
        );
      }
    }
  }

  return (
    <div className="pa-files">
      <div
        className={over ? "pa-drop is-drag" : "pa-drop"}
        onDragEnter={() => setOver(true)}
        onDragOver={(event) => {
          event.preventDefault();
          setOver(true);
        }}
        onDragLeave={() => setOver(false)}
        onDrop={(event) => {
          event.preventDefault();
          setOver(false);
          const dropped = Array.from(event.dataTransfer.files).filter(
            (file) => file instanceof File,
          );
          if (dropped.length) void add(dropped);
        }}
      >
        <div className="pa-drop-copy">
          <CloudUpload className="size-8" />
          <strong>Drop course files here</strong>
          <span>PDF, DOCX, PPTX, POTX, HTML, HTM, TXT, MD, up to 25 MB</span>
        </div>
        <Button type="button" variant="outline" size="sm" onClick={() => picker.current?.click()}>
          Browse files
        </Button>
        <input
          ref={picker}
          type="file"
          accept={ACCEPT}
          multiple
          className="sr-only"
          onChange={(event) => {
            const chosen = Array.from(event.target.files ?? []);
            event.target.value = "";
            if (chosen.length) void add(chosen);
          }}
        />
      </div>
      <ul className="pa-file-list">
        {shown.map((file) => (
          <li key={file.id || file.filename} className="pa-file-row">
            <FileIcon name={file.filename} />
            <FileTypeBadge name={file.filename} />
            <span className="pa-file-name">{file.filename}</span>
            <span className="pa-file-size">{file.size ? formatSize(file.size) : ""}</span>
            <InsightBadge status={file.insight_status} />
            <KindBadge kind={file.kind} />
            {file.tags?.slice(0, 2).map((tag) => (
              <Badge
                key={tag}
                className={`${TONES.slate} max-w-[8rem] truncate px-1.5 py-0 text-[10px] font-normal`}
              >
                {tag}
              </Badge>
            ))}
            {file.phase === "uploading" && (
              <Progress className="w-[120px]" aria-label="Uploading" value={file.progress || 35} />
            )}
            {file.phase === "error" && <Badge className={TONES.red}>{file.error || "Error"}</Badge>}
            {file.phase !== "uploading" && file.phase !== "error" && file.status !== "error" && (
              <Badge className={TONES.green}>Ready</Badge>
            )}
            {file.scrubbed && <Badge className={TONES.blue}>Personal data removed</Badge>}
            {file.status === "quarantined" && (
              <Badge className={TONES.red}>Needs another look</Badge>
            )}
            <Button
              type="button"
              variant="ghost"
              size="icon-sm"
              aria-label="Remove"
              title="Remove"
              onClick={() => {
                setLocal((current) => current.filter((item) => item.id !== file.id));
                if (file.id && file.phase !== "uploading" && file.phase !== "error")
                  void onRemove(file);
              }}
            >
              <Trash2 />
            </Button>
          </li>
        ))}
      </ul>
      {onInstructions && (
        <div className="pa-instruct">
          <div className="grid gap-2">
            <Label htmlFor="instructions">Instructions to AI</Label>
            <Textarea
              id="instructions"
              className="min-h-24"
              value={instructions || ""}
              rows={4}
              onChange={(event) => onInstructions(event.target.value)}
            />
            <p className="text-muted-foreground text-xs">
              {(instructions || "").length} characters. These stay with this course and are applied
              on the later steps.
            </p>
          </div>
          <div className="pa-chips">
            {EXAMPLES.map((example) => (
              <Button
                key={example}
                type="button"
                variant="ghost"
                size="sm"
                onClick={() =>
                  onInstructions(instructions ? `${instructions.trim()} ${example}` : example)
                }
              >
                {example}
              </Button>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}

function FileIcon({ name }: { name: string }) {
  const lower = name.toLowerCase();
  if (lower.endsWith(".pdf")) return <FileText className="size-5" />;
  if (lower.endsWith(".docx")) return <FileType2 className="size-5" />;
  if (lower.endsWith(".pptx") || lower.endsWith(".potx"))
    return <Presentation className="size-5" />;
  if (lower.endsWith(".html") || lower.endsWith(".htm")) return <FileCode className="size-5" />;
  if (lower.endsWith(".txt") || lower.endsWith(".md")) return <FileText className="size-5" />;
  return <FileGlyph className="size-5" />;
}

function FileTypeBadge({ name }: { name: string }) {
  const ext = extensionOf(name);
  return (
    <Badge className={`${fileTone(ext)} px-1.5 py-0 text-[10px] tracking-wide uppercase`}>
      {ext}
    </Badge>
  );
}

function extensionOf(name: string) {
  const ext = /\.([a-z0-9]+)$/i.exec(name)?.[1];
  return ext ? ext.toUpperCase() : "FILE";
}

function fileTone(ext: string) {
  switch (ext) {
    case "PDF":
      return TONES.red;
    case "DOCX":
      return TONES.blue;
    case "PPTX":
    case "POTX":
      return TONES.amber;
    case "HTML":
    case "HTM":
      return TONES.violet;
    case "TXT":
    case "MD":
      return TONES.slate;
    default:
      return TONES.slate;
  }
}

function formatSize(bytes: number) {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${Math.max(1, Math.round(bytes / 1024))} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

function InsightBadge({ status }: { status?: string }) {
  const badge = insightBadge(status);
  if (!badge) return null;
  return (
    <Badge className={`${BADGE_TONE[badge.tone]} px-1.5 py-0 text-[10px]`}>{badge.label}</Badge>
  );
}

function KindBadge({ kind }: { kind?: string }) {
  const label = kindLabel(kind);
  if (!label) return null;
  return <Badge className={`${BADGE_TONE[kindTone(kind)]} px-1.5 py-0 text-[10px]`}>{label}</Badge>;
}
