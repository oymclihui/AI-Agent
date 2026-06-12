"use client";

import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import rehypeHighlight from "rehype-highlight";
import { clsx } from "clsx";
import type { Components } from "react-markdown";

export type MarkdownViewSize = "xs" | "sm" | "md" | "lg";

interface MarkdownViewProps {
  children: string;
  className?: string;
  size?: MarkdownViewSize;
  /** Disable syntax highlighting for very long streaming chunks */
  highlight?: boolean;
}

const SIZE_CLASS: Record<MarkdownViewSize, string> = {
  xs: "markdown-body markdown-body-xs",
  sm: "markdown-body markdown-body-sm",
  md: "markdown-body markdown-body-md",
  lg: "markdown-body markdown-body-lg",
};

function buildComponents(): Components {
  return {
    h1: ({ children }) => <h1 className="md-h1">{children}</h1>,
    h2: ({ children }) => <h2 className="md-h2">{children}</h2>,
    h3: ({ children }) => <h3 className="md-h3">{children}</h3>,
    h4: ({ children }) => <h4 className="md-h4">{children}</h4>,
    p: ({ children }) => <p className="md-p">{children}</p>,
    ul: ({ children }) => <ul className="md-ul">{children}</ul>,
    ol: ({ children }) => <ol className="md-ol">{children}</ol>,
    li: ({ children }) => <li className="md-li">{children}</li>,
    blockquote: ({ children }) => <blockquote className="md-blockquote">{children}</blockquote>,
    hr: () => <hr className="md-hr" />,
    a: ({ href, children }) => (
      <a href={href} className="md-a" target="_blank" rel="noopener noreferrer">
        {children}
      </a>
    ),
    table: ({ children }) => (
      <div className="md-table-wrap">
        <table className="md-table">{children}</table>
      </div>
    ),
    thead: ({ children }) => <thead className="md-thead">{children}</thead>,
    tbody: ({ children }) => <tbody>{children}</tbody>,
    tr: ({ children }) => <tr className="md-tr">{children}</tr>,
    th: ({ children }) => <th className="md-th">{children}</th>,
    td: ({ children }) => <td className="md-td">{children}</td>,
    code: ({ className, children, ...props }) => {
      const text = String(children).replace(/\n$/, "");
      const isBlock = className?.includes("language-") || text.includes("\n");
      if (isBlock) {
        return (
          <code className={clsx("md-code-block", className)} {...props}>
            {children}
          </code>
        );
      }
      return (
        <code className="md-code-inline" {...props}>
          {children}
        </code>
      );
    },
    pre: ({ children }) => <pre className="md-pre">{children}</pre>,
    strong: ({ children }) => <strong className="md-strong">{children}</strong>,
    em: ({ children }) => <em className="md-em">{children}</em>,
    img: ({ src, alt }) => (
      // eslint-disable-next-line @next/next/no-img-element
      <img src={src} alt={alt ?? ""} className="md-img" loading="lazy" />
    ),
  };
}

const COMPONENTS = buildComponents();

export default function MarkdownView({
  children,
  className,
  size = "sm",
  highlight = true,
}: MarkdownViewProps) {
  if (!children?.trim()) return null;

  return (
    <article className={clsx(SIZE_CLASS[size], className)}>
      <ReactMarkdown
        remarkPlugins={[remarkGfm]}
        rehypePlugins={highlight ? [rehypeHighlight] : []}
        components={COMPONENTS}
      >
        {children}
      </ReactMarkdown>
    </article>
  );
}
