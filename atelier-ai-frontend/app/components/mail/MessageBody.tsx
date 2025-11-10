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
        <div key={index}>{line}</div>
      ))}
    </div>
  );
}
