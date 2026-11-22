"use client";

import { useState } from "react";
import {
  Button,
  FileUploaderDropContainer,
  FileUploaderItem,
  ProgressBar,
  Tag,
  TextArea,
} from "@carbon/react";
import {
  CloudUpload,
  Document,
  DocumentPdf,
  DocumentWordProcessor,
  PresentationFile,
} from "@carbon/icons-react";

export interface CourseFile {
  id: string;
  filename: string;
  status: string;
  size?: number;
  scrubbed?: boolean;
  phase?: "uploading" | "ready" | "error";
  progress?: number;
  error?: string;
}

const EXAMPLES = [
  "Focus on healthcare cases.",
  "Prefer a project a group can build in four weeks.",
  "Keep the assessments to four tasks that total 100%.",
  "Use the faculty wording for integrity and attendance.",
];

const LIMIT = 25 * 1024 * 1024;

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
  const known = new Set(files.map((file) => file.filename));
  const pending = local.filter((file) => file.phase === "uploading" || file.phase === "error" || !known.has(file.filename));
  const shown = [...pending, ...files];

  async function add(incoming: File[]) {
    for (const file of incoming) {
      const id = `${file.name}-${file.size}-${Date.now()}`;
      if (file.size > LIMIT) {
        setLocal((current) => [
          { id, filename: file.name, status: "error", size: file.size, phase: "error", error: "That file is over 25 MB." },
          ...current,
        ]);
        continue;
      }
      const allowed = [".pdf", ".docx", ".pptx", ".txt", ".md"];
      if (!allowed.some((ext) => file.name.toLowerCase().endsWith(ext))) {
        setLocal((current) => [
          { id, filename: file.name, status: "error", size: file.size, phase: "error", error: "Use a PDF, DOCX, PPTX, or TXT file." },
          ...current,
        ]);
        continue;
      }
      setLocal((current) => [{ id, filename: file.name, status: "uploading", size: file.size, phase: "uploading", progress: 35 }, ...current]);
      try {
        await onUpload(file);
        setLocal((current) =>
          current.map((item) => (item.id === id ? { ...item, phase: "ready", status: "ready", progress: 100 } : item)),
        );
      } catch (err) {
        const message = err instanceof Error ? err.message : "The upload failed.";
        setLocal((current) => current.map((item) => (item.id === id ? { ...item, phase: "error", status: "error", error: message } : item)));
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
        onDrop={() => setOver(false)}
      >
        <div className="pa-drop-copy">
          <CloudUpload size={32} />
          <strong>Drop course files here</strong>
          <span>PDF, DOCX, PPTX or TXT, up to 25 MB</span>
        </div>
        <FileUploaderDropContainer
          accept={[".pdf", ".docx", ".pptx", ".txt", ".md"]}
          labelText="Browse files"
          multiple
          onAddFiles={(_event, content) => {
            setOver(false);
            const added = content.addedFiles.filter((file) => file instanceof File) as File[];
            void add(added);
          }}
        />
      </div>
      <ul className="pa-file-list">
        {shown.map((file) => (
          <li key={file.id || file.filename}>
            <span className="pa-file-icon" aria-hidden>
              <FileIcon name={file.filename} />
            </span>
            <div className="pa-file-main">
              <FileUploaderItem
                name={`${file.filename}${file.size ? ` · ${formatSize(file.size)}` : ""}`}
                status={file.phase === "uploading" ? "uploading" : "complete"}
                invalid={file.phase === "error"}
                errorSubject="Could not add this file"
                errorBody={file.error}
                iconDescription={file.phase === "error" ? "Error" : file.phase === "uploading" ? "Uploading" : "Ready"}
                onDelete={() => {
                  setLocal((current) => current.filter((item) => item.id !== file.id));
                  if (file.id && file.phase !== "uploading" && file.phase !== "error") void onRemove(file);
                }}
              />
              {file.phase === "uploading" && (
                <ProgressBar label="Uploading" value={file.progress || 35} size="small" />
              )}
              <div className="pa-file-tags">
                {file.phase !== "uploading" && file.phase !== "error" && file.status !== "error" && (
                  <Tag type="green" size="sm">Ready</Tag>
                )}
                {file.scrubbed && <Tag type="blue" size="sm">Personal data removed</Tag>}
                {file.status === "quarantined" && <Tag type="red" size="sm">Needs another look</Tag>}
              </div>
            </div>
          </li>
        ))}
      </ul>
      {onInstructions && (
        <div className="pa-instruct">
          <TextArea
            id="instructions"
            labelText="Instructions to AI"
            helperText={`${(instructions || "").length} characters. These stay with this course and are applied on the later steps.`}
            value={instructions || ""}
            rows={4}
            onChange={(event) => onInstructions(event.target.value)}
          />
          <div className="pa-chips">
            {EXAMPLES.map((example) => (
              <Button
                key={example}
                kind="ghost"
                size="sm"
                onClick={() => onInstructions(instructions ? `${instructions.trim()} ${example}` : example)}
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
  if (lower.endsWith(".pdf")) return <DocumentPdf size={20} />;
  if (lower.endsWith(".docx")) return <DocumentWordProcessor size={20} />;
  if (lower.endsWith(".pptx")) return <PresentationFile size={20} />;
  return <Document size={20} />;
}

function formatSize(bytes: number) {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${Math.max(1, Math.round(bytes / 1024))} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}
