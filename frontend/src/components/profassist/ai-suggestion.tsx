"use client";

import { Check, RotateCw } from "lucide-react";
import { CodeBlock } from "@/components/ai-elements/code-block";
import { InlineCitation, InlineCitationText } from "@/components/ai-elements/inline-citation";
import { MessageResponse } from "@/components/ai-elements/message";
import { Plan, PlanContent, PlanDescription, PlanHeader, PlanTitle } from "@/components/ai-elements/plan";
import { Shimmer } from "@/components/ai-elements/shimmer";
import { Task, TaskContent, TaskItem, TaskTrigger } from "@/components/ai-elements/task";
import { Artifact, ArtifactAction, ArtifactActions, ArtifactContent, ArtifactDescription, ArtifactHeader, ArtifactTitle } from "@/components/ai-elements/artifact";

export function AiSuggestion({
  title,
  description,
  body,
  busy,
  citation,
  onAccept,
  onRegenerate,
}: {
  title: string;
  description: string;
  body: string;
  busy?: boolean;
  citation?: string;
  onAccept?: () => void;
  onRegenerate?: () => void;
}) {
  return (
    <div className="pa-ai" style={{ marginTop: "1rem" }}>
      {busy ? (
        <Shimmer>Drafting from the attachments and your instructions…</Shimmer>
      ) : (
        <Artifact>
          <ArtifactHeader>
            <div>
              <ArtifactTitle>{title}</ArtifactTitle>
              <ArtifactDescription>{description}</ArtifactDescription>
            </div>
            <ArtifactActions>
              {onAccept && (
                <ArtifactAction tooltip="Accept" label="Accept" onClick={onAccept}>
                  <Check />
                </ArtifactAction>
              )}
              {onRegenerate && (
                <ArtifactAction tooltip="Regenerate" label="Regenerate" onClick={onRegenerate}>
                  <RotateCw />
                </ArtifactAction>
              )}
            </ArtifactActions>
          </ArtifactHeader>
          <ArtifactContent className="grid gap-4 p-4">
            <Plan defaultOpen>
              <PlanHeader>
                <div>
                  <PlanTitle>Plan</PlanTitle>
                  <PlanDescription>Read the files, then the instructions, then this step.</PlanDescription>
                </div>
              </PlanHeader>
              <PlanContent>The privacy gate runs before the drafter. Citations name the file, not a student.</PlanContent>
            </Plan>
            <Task defaultOpen>
              <TaskTrigger title="Steps the drafter took" />
              <TaskContent>
                <TaskItem>Match the step to the subject outline.</TaskItem>
                <TaskItem>Prefer the professor&apos;s instructions when they disagree with the default.</TaskItem>
              </TaskContent>
            </Task>
            <MessageResponse>{body}</MessageResponse>
            {citation && (
              <InlineCitation>
                <InlineCitationText>{citation}</InlineCitationText>
              </InlineCitation>
            )}
            <CodeBlock code={body.slice(0, 400)} language="markdown" />
          </ArtifactContent>
        </Artifact>
      )}
    </div>
  );
}
