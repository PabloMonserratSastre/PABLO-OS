import { ReactNode } from "react";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import {
  Empty,
  EmptyDescription,
  EmptyHeader,
  EmptyTitle,
} from "@/components/ui/empty";
import { labels } from "./api";
export function Choice({
  value,
  onChange,
  options,
  label,
}: {
  value: string;
  onChange: (value: string) => void;
  options: (string | [string, string])[];
  label: string;
}) {
  return (
    <Select value={value} onValueChange={onChange}>
      <SelectTrigger aria-label={label}>
        <SelectValue />
      </SelectTrigger>
      <SelectContent>
        {options.map((option) => {
          const [id, text] = Array.isArray(option)
            ? option
            : [option, labels[option] || option];
          return (
            <SelectItem key={id} value={id}>
              {text}
            </SelectItem>
          );
        })}
      </SelectContent>
    </Select>
  );
}
export function Blank({
  title,
  children,
}: {
  title: string;
  children?: ReactNode;
}) {
  return (
    <Empty className="empty-state">
      <EmptyHeader>
        <EmptyTitle>{title}</EmptyTitle>
        <EmptyDescription>{children}</EmptyDescription>
      </EmptyHeader>
    </Empty>
  );
}
export function Badge({ value }: { value: string }) {
  return (
    <span
      className={
        "badge " +
        (["DONE", "COMPLETED", "CONNECTED", "AVAILABLE"].includes(value)
          ? "good"
          : ["WAITING_APPROVAL", "HIGH", "NEEDS_AUTH", "FAILED"].includes(value)
            ? "warm"
            : "")
      }
    >
      {labels[value] || value}
    </span>
  );
}
export function withoutSynthesis(text: string) {
  return text.split(/\n\s*\*\*Síntesis IA\*\*\s*\n/)[0].trimEnd();
}
export function RichText({ text }: { text: string }) {
  // Safe subset: no raw HTML, images or arbitrary links from untrusted model output.
  return (
    <div className="rich">
      {text.split("```").map((part, i) =>
        i % 2 ? (
          <pre key={i}>
            <code>{part.replace(/^\w+\n/, "")}</code>
          </pre>
        ) : (
          <div key={i}>
            {part.split("\n").map((line, j) => (
              <p key={j}>
                {line.split(/(\*\*.*?\*\*)/g).map((s, k) =>
                  s.startsWith("**") ? (
                    <strong key={k}>{s.slice(2, -2)}</strong>
                  ) : (
                    s.split(/(https?:\/\/[^\s<>]+)/g).map((piece, index) =>
                      /^https?:\/\//.test(piece) ? (
                        <a
                          key={index}
                          href={piece}
                          target="_blank"
                          rel="noopener noreferrer"
                        >
                          {piece}
                        </a>
                      ) : (
                        piece
                      ),
                    )
                  ),
                )}
              </p>
            ))}
          </div>
        ),
      )}
    </div>
  );
}
