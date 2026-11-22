"use client";

import { Checkmark, Renew } from "@carbon/icons-react";
import { CodeBlock } from "@/components/ai-elements/code-block";
import {
  InlineCitation,
  InlineCitationCard,
  InlineCitationCardBody,
  InlineCitationCardTrigger,
  InlineCitationCarousel,
  InlineCitationCarouselContent,
  InlineCitationCarouselItem,
  InlineCitationQuote,
  InlineCitationSource,
  InlineCitationText,
} from "@/components/ai-elements/inline-citation";
import { MessageResponse } from "@/components/ai-elements/message";
import { Plan, PlanContent, PlanDescription, PlanHeader, PlanTitle } from "@/components/ai-elements/plan";
import { Shimmer } from "@/components/ai-elements/shimmer";
import { Source, Sources, SourcesContent, SourcesTrigger } from "@/components/ai-elements/sources";
import { Task, TaskContent, TaskItem, TaskTrigger } from "@/components/ai-elements/task";
import { WebPreview, WebPreviewBody, WebPreviewNavigation, WebPreviewUrl } from "@/components/ai-elements/web-preview";
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
  const source = "https://demo.uowd.ac.ae/materials/lecture-note";
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
                  <Checkmark />
                </ArtifactAction>
              )}
              {onRegenerate && (
                <ArtifactAction tooltip="Regenerate" label="Regenerate" onClick={onRegenerate}>
                  <Renew />
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
                <TaskItem>Prefer the professor's instructions when they disagree with the default.</TaskItem>
              </TaskContent>
            </Task>
            <MessageResponse>{body}</MessageResponse>
            <InlineCitation>
              <InlineCitationText>{citation || "Lecture note"}</InlineCitationText>
              <InlineCitationCard>
                <InlineCitationCardTrigger sources={[source]} />
                <InlineCitationCardBody>
                  <InlineCitationCarousel>
                    <InlineCitationCarouselContent>
                      <InlineCitationCarouselItem>
                        <InlineCitationSource title="Uploaded note" description="Indexed for this professor and course." />
                        <InlineCitationQuote>{citation || body.slice(0, 180)}</InlineCitationQuote>
                      </InlineCitationCarouselItem>
                    </InlineCitationCarouselContent>
                  </InlineCitationCarousel>
                </InlineCitationCardBody>
              </InlineCitationCard>
            </InlineCitation>
            <Sources>
              <SourcesTrigger count={1} />
              <SourcesContent>
                <Source href={source} title="Lecture note" />
              </SourcesContent>
            </Sources>
            <CodeBlock code={body.slice(0, 400)} language="markdown" />
            <WebPreview defaultUrl={source} className="h-40">
              <WebPreviewNavigation>
                <WebPreviewUrl readOnly />
              </WebPreviewNavigation>
              <WebPreviewBody
                srcDoc={`<p style="font-family:IBM Plex Sans,sans-serif;padding:1rem">${body.slice(0, 280)}</p>`}
              />
            </WebPreview>
          </ArtifactContent>
        </Artifact>
      )}
    </div>
  );
}
