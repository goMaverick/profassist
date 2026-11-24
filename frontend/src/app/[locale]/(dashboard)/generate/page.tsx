"use client";

import { useEffect, useState } from "react";
import { Plus, WandSparkles } from "lucide-react";

import { AiSuggestion } from "@/components/profassist/ai-suggestion";
import { pa, run } from "@/components/profassist/bits";
import { CouncilStage } from "@/components/profassist/council-stage";
import {
  Alert,
  AlertDescription,
  AlertTitle,
  Badge,
  Button,
  Card,
  Checkbox,
  Label,
} from "@/components/ui";
import { cn } from "@/lib/utils";

interface Outline {
  id: string;
  code: string;
  name: string;
  body: {
    clos?: Array<{ code: string; text: string }>;
    tasks?: Array<{ number: string; name: string; weight: number }>;
  };
}
interface Suggestion {
  number: string;
  name: string;
  task_type: string;
  weight: number;
  due: string;
  lo_codes: string[];
  brief: string;
  criteria: Array<{ name: string; weight: number }>;
}

const BADGE_TONE = {
  purple: "border-purple-500/40 bg-purple-500/10 text-purple-700",
  blue: "border-blue-500/40 bg-blue-500/10 text-blue-700",
  teal: "border-teal-500/40 bg-teal-500/10 text-teal-700",
  green: "border-emerald-500/40 bg-emerald-500/10 text-emerald-700",
} as const;

export default function GeneratePage() {
  const [outlines, setOutlines] = useState<Outline[]>([]);
  const [current, setCurrent] = useState<Outline | null>(null);
  const [selected, setSelected] = useState<string[]>([]);
  const [suggestions, setSuggestions] = useState<Suggestion[]>([]);
  const [error, setError] = useState("");
  const [note, setNote] = useState("");
  const [talking, setTalking] = useState(false);

  useEffect(() => {
    pa<{ items: Outline[] }>("/outlines")
      .then((data) => {
        setOutlines(data.items);
        setCurrent(data.items[0] || null);
      })
      .catch((err: unknown) => setError(err instanceof Error ? err.message : "No courses yet"));
  }, []);

  const clos = current?.body.clos || [];

  return (
    <div className="grid gap-6 lg:grid-cols-[minmax(0,5fr)_minmax(0,11fr)]">
      {error && (
        <div className="lg:col-span-2">
          <Alert variant="destructive">
            <AlertTitle>Assessments</AlertTitle>
            <AlertDescription>{error}</AlertDescription>
          </Alert>
        </div>
      )}
      {note && (
        <div className="lg:col-span-2">
          <Alert variant="success">
            <AlertTitle>Saved</AlertTitle>
            <AlertDescription>{note}</AlertDescription>
          </Alert>
        </div>
      )}
      <div>
        <h2 className="text-base">Course</h2>
        {outlines.map((item) => (
          <Card
            key={item.id}
            className={cn("mb-2 p-4", current?.id === item.id && "ring-primary ring-2")}
          >
            <button
              type="button"
              className="w-full cursor-pointer text-left"
              onClick={() => {
                setCurrent(item);
                setSelected([]);
                setSuggestions([]);
              }}
            >
              <strong>{item.code}</strong>
              <div>{item.name}</div>
            </button>
          </Card>
        ))}
      </div>
      <div>
        <h2 className="text-base">Course learning outcomes</h2>
        {clos.map((item) => (
          <div key={item.code} className="flex items-start gap-2 py-1">
            <Checkbox
              id={item.code}
              className="mt-0.5"
              checked={selected.includes(item.code)}
              onCheckedChange={(checked) =>
                setSelected((currentCodes) =>
                  checked
                    ? [...currentCodes, item.code]
                    : currentCodes.filter((code) => code !== item.code),
                )
              }
            />
            <Label htmlFor={item.code} className="leading-5 font-normal">
              {`${item.code} ${item.text}`}
            </Label>
          </div>
        ))}
        <div className="mt-4 flex gap-2">
          <Button
            data-ask-council=""
            disabled={!current || selected.length === 0}
            onClick={async () => {
              if (!current) return;
              setTalking(true);
              const data = await run(
                () =>
                  pa<{ suggestions: Suggestion[] }>(`/outlines/${current.id}/assessments/suggest`, {
                    method: "POST",
                    body: JSON.stringify({ lo_codes: selected }),
                  }),
                setError,
              );
              if (data) setSuggestions(data.suggestions);
              setTalking(false);
            }}
          >
            <WandSparkles />
            Ask the council
          </Button>
          <Button
            variant="secondary"
            data-accept-assessments=""
            disabled={!current || suggestions.length === 0}
            onClick={async () => {
              if (!current) return;
              const next = await run(
                () =>
                  pa<Outline>(`/outlines/${current.id}/assessments/accept`, {
                    method: "POST",
                    body: JSON.stringify({ tasks: suggestions }),
                  }),
                setError,
              );
              if (next) {
                setCurrent(next);
                setOutlines((items) => items.map((item) => (item.id === next.id ? next : item)));
                setNote(
                  "The assignment is numbered and linked to the outcomes. Open Rubric or Grade to use it.",
                );
              }
            }}
          >
            <Plus />
            Accept
          </Button>
        </div>
        {talking && <CouncilStage scene="assessment" />}
        {(talking || suggestions.length > 0) && (
          <AiSuggestion
            title="Assessment suggestion"
            description="The council drafted a task from the outcomes you picked."
            body={
              suggestions
                .map((item) => `${item.name} (${item.weight}%). ${item.brief}`)
                .join("\n\n") || "The council is reading the outcomes."
            }
            busy={talking}
            onRegenerate={() => {
              document.querySelector<HTMLButtonElement>("[data-ask-council]")?.click();
            }}
            onAccept={() => {
              document.querySelector<HTMLButtonElement>("[data-accept-assessments]")?.click();
            }}
          />
        )}
        {suggestions.map((item) => (
          <Card key={item.name} className="mt-4 p-4">
            <div className="mb-2 flex flex-wrap gap-1">
              <Badge variant="outline" className={BADGE_TONE.purple}>
                {item.task_type}
              </Badge>
              <Badge variant="outline" className={BADGE_TONE.blue}>
                {item.weight}%
              </Badge>
              <Badge variant="outline" className={BADGE_TONE.teal}>
                {item.due}
              </Badge>
            </div>
            <h3 className="mb-1 font-medium">{item.name}</h3>
            <p>{item.brief}</p>
            <p className="text-muted-foreground">Outcomes: {item.lo_codes.join(", ")}</p>
            <ul className="list-disc pl-5">
              {item.criteria.map((criterion) => (
                <li key={criterion.name}>
                  {criterion.name} ({criterion.weight}%)
                </li>
              ))}
            </ul>
          </Card>
        ))}
        <h2 className="mt-6 text-base">Already on this course</h2>
        <div className="flex flex-wrap gap-1">
          {(current?.body.tasks || []).map((item) => (
            <Badge key={item.number} variant="outline" className={BADGE_TONE.green}>
              {item.number} {item.name} {item.weight}%
            </Badge>
          ))}
        </div>
      </div>
    </div>
  );
}
