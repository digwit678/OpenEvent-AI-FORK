import React from 'react';

interface MessageLike {
  render_body?: string;
  body_markdown?: string;
  body_md?: string;
  body?: string;
  prompt?: string;
}

interface MessageBodyProps {
  msg: MessageLike;
}

function normaliseMarkdown(text: string): string {
  let output = text;
  output = output.replace(/^###\s+/gm, '');
  output = output.replace(/\*\*(.*?)\*\*/g, '$1');
  output = output.replace(/_(.*?)_/g, '$1');
  return output;
}

function parseLineWithLinks(line: string, lineIndex: number): JSX.Element {
  // Match anchor tags: <a href="..." target="_blank" rel="noopener noreferrer">...</a>
  const anchorRegex = /<a\s+href="([^"]+)"[^>]*>(.*?)<\/a>/g;
  const parts: (string | JSX.Element)[] = [];
  let lastIndex = 0;
  let match;
  let keyCounter = 0;

  while ((match = anchorRegex.exec(line)) !== null) {
    // Add text before the link
    if (match.index > lastIndex) {
      parts.push(line.substring(lastIndex, match.index));
    }

    // Add the link as a clickable anchor
    const href = match[1];
    const linkText = match[2];
    parts.push(
      <a
        key={`${lineIndex}-link-${keyCounter++}`}
        href={href}
        target="_blank"
        rel="noopener noreferrer"
        style={{ color: '#0066cc', textDecoration: 'underline', cursor: 'pointer' }}
      >
        {linkText}
      </a>
    );

    lastIndex = anchorRegex.lastIndex;
  }

  // Add remaining text after the last link
  if (lastIndex < line.length) {
    parts.push(line.substring(lastIndex));
  }

  // If no links were found, return the line as-is
  if (parts.length === 0) {
    return <>{line}</>;
  }

  return <>{parts}</>;
}

export default function MessageBody({ msg }: MessageBodyProps): JSX.Element {
  const raw =
    msg.body_markdown ??
    msg.body_md ??
    msg.render_body ??
    msg.body ??
    msg.prompt ??
    '';

  const text = normaliseMarkdown(raw);

  const lines = text.split('\n');

  return (
    <div className="message-body" style={{ whiteSpace: 'pre-wrap' }}>
      {lines.map((line, index) => (
        <div key={index}>{parseLineWithLinks(line, index)}</div>
      ))}
    </div>
  );
}
